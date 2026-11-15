# Architecture

A modular monolith: one FastAPI process, one SQLite file, one React single-page app. No queues, no microservices.

## The rule the design is built around

Three kinds of information are kept apart, and each has exactly one owner.

| Kind | Owner | May an LLM produce it? |
|---|---|---|
| Financial figures (EMI, DSCR, FOIR, APR, totals) | `calculations.py` | No |
| Lender decisions and eligibility | `lenders.py` evaluating `data/lenders.json` | No |
| Ranking | `recommendations.py`, disclosed weights | No |
| Findings and their evidence | `analysis.py`, from extracted documents | No |
| Explanations, summaries, drafts | An AI provider through `integrations/` | Yes, validated and labelled |

Source-of-truth order, shown in the UI as a label beside each figure: verified source document → confirmed by the
borrower → calculated → versioned lender rule → expert-approved knowledge → AI text.

## The synthetic environment: three layers

```
Layer B  synthetic.py      ground-truth dataset per scenario (transactions with true categories, returns, loans)
            │  docgen.py renders it
            ▼
Layer A  PDF files         what the borrower "submitted": 48 documents for the primary case
            │  extraction.py reads the PDF text
            ▼
Layer C  analysis.py       classification, reconciliation, findings: computed from the documents alone
```

- A scenario is a small set of explicit parameters, including its deliberate discrepancies. `build_dataset` expands
  it with a seeded RNG and no clock, so the same scenario always gives the same dataset and byte-identical PDFs.
- `extraction.py`, `analysis.py`, `investigation.py`, `lenders.py`, `restructuring.py` and `recommendations.py` never
  import `synthetic.py`, `docgen.py` or `environment.py`. A test enforces this by parsing their imports.
- Layer B is used only to generate documents and, in the demo control centre, to compare the investigation's results
  with the truth (`GET /api/demo/ground-truth/{case}`). It is never served on a borrower route.
- The analysis classifies bank transactions from narration alone. Credits with no invoice reference or known pattern
  are left out of sales and turned into questions for the borrower.

Scenario library: the Tiruppur textile wholesaler (primary), plus high EMI burden, GST/bank mismatch, low business
vintage, incomplete documentation and collateral-backed need. A borrower who onboards themselves gets a pack built
from their own answers (`scenario_from_profile`).

## Database (`db.py`)

SQLite, one connection per request or background task.

| Table | Holds |
|---|---|
| `borrowers` | Onboarding answers (validated `BorrowerProfile` JSON) |
| `cases` | One per borrower. `data` JSON holds consents, investigation (task states and result), answers, corrections, restructuring scenario, selection, proposal, application, escalation, advisor notes |
| `documents` | One row per PDF: type, group, path, source (synthetic or upload), extraction output |
| `lender_products` | The fictional policies, seeded from `data/lenders.json`, editable, versioned |
| `events` | Application timeline (simulated), audit trail, logs |
| `knowledge` | Expert knowledge entries with status and version |
| `settings` | Runtime switches (AI mode) |

`PRAGMA user_version` holds a schema version. When it changes, derived tables and demo rows are rebuilt at start-up;
borrowers created through onboarding are kept. Case updates are read-modify-write inside `BEGIN IMMEDIATE`, so the
background investigation and a request cannot overwrite each other. Files live in `files/` beside the database.

## Request flow

```
React page → api/services.ts → fetch → FastAPI route (routes.py) → service module → db.py
                                                   │
                                  Pydantic response_model on every route
```

- `schemas.py` is the contract. `npm run gen:types` generates `frontend/src/api/schema.d.ts` from the backend's
  OpenAPI document; the frontend has no hand-written API types, so the two cannot drift silently.
- Errors: services raise `NotFound`, `Conflict`, `Forbidden` or `BadInput`; `main.py` maps them to 404, 409, 403 and
  422 with a human-readable `detail`. Anything unexpected becomes a 500 with a safe message and a log event.
- The frontend's `request()` turns those into typed `ApiError`s; pages show the server's wording.

## Investigation (`investigation.py`)

`POST /api/cases/{id}/investigation/run` requires the borrower's consent, marks nine tasks as queued and starts a
FastAPI background task. Each task is marked running, does its work, and is marked complete, needs input or failed in
the case record. The page polls `GET .../investigation` every 500 ms. The states are real; the only artificial element
is an optional pause between steps (`LOANKART_DEMO_PACING_MS`), which the page discloses.

Answering a question or an advisor correction calls `recompute`, which re-runs the analysis from stored extractions
without re-reading PDFs. A run ID guards against a stale run writing over a newer one or a reset.

## Financial engine (`calculations.py`)

Pure functions on `Decimal`. Rupee amounts round half-up to whole rupees; ratios to two decimals. Formulas are in the
module docstring. No function applies a threshold: thresholds belong to lender policies. APR is the annualised monthly
IRR of the amount received after fees, found by bisection.

## Lender simulator (`lenders.py`)

`evaluate(product, facts)` is pure and deterministic. `facts` are documented figures only, never the borrower's
estimates. Steps, in a fixed order of precedence:

1. Eligibility rules (business age, minimum sales, GST, EMI returns, late filings, running loans, purpose). A failure is a rejection.
2. Security: accepted type and valuation.
3. Income as that lender assesses it: bank-statement surplus, ITR income, or a share of GST turnover.
4. The largest amount the policy supports: the minimum of the product cap, sales multiple, loan-to-value, FOIR room and DSCR room.
5. One of nine decisions, with every rule listed as met, not met or unresolved, and the cost of the suggested amount.

The same borrower therefore gets different outcomes from different lenders, for reasons that can be read off the rules.

## Restructuring (`restructuring.py`)

`apply(inputs, facts, obligations)` turns a chosen scenario into the facts a lender would see. `compute` returns the
current and proposed positions and the eight dimensions (amount, tenure, existing loans, security, loan type, evidence,
co-applicant, documentation), each with current state, proposed change, EMI and total-repayment impact, costs, risks,
evidence needed and how many simulated products it opens. Nothing is applied unless the borrower chooses it.

## Recommendations (`recommendations.py`)

Every product is evaluated. Viable ones that cover at least 30% of the need are scored 0 to 100 as a weighted sum of
six factors: coverage, affordability, cost, evidence completeness, collateral exposure and speed. Five weight presets
correspond to the borrower's stated priority; the weights are shown on the page. Ties break by APR then product ID.
Everything else is listed as unsuitable with its reason. With no viable option, a recovery plan is built from the
blocking reasons. Each option carries four separately labelled sources: simulated criteria, approved expert notes,
synthetic history, and optional AI commentary.

## Application simulation (`workflow.py`)

Selecting an option creates a proposal (structure, figures used, checklist, three approval checkpoints, draft PDF).
Submission creates a simulated application with a reference derived from the case and product. `advance` is one
deterministic step of the simulator: the first review raises up to two routine queries derived from the findings; once
answered, the product is re-evaluated and the result is an offer, a further query, human review or a rejection.
Every event is stored with `simulated = true` and titled "(simulated)". Demo control can force a query, a rejection
or an alternative offer.

## AI providers (`integrations/`)

```
base.py     interfaces (ReasoningProvider, SpeechProvider, TranslationProvider, DocumentProvider), output schemas,
            the shared system prompt and task prompts
mock.py     MockAIProvider: deterministic text assembled only from the evidence it is given
claude.py   ClaudeReasoningProvider: Anthropic SDK, structured outputs (messages.parse), server-side refusal fallback
sarvam.py   SarvamChatProvider, SarvamSpeechProvider, SarvamTranslationProvider, SarvamDocumentProvider
paytm.py    synthetic merchant fixture summary; LivePaytmEvidence (Paytm's Settlement Summary request, not yet wired in)
__init__.py AIService: mode, provider choice, validation, retry, fallback, logging, status and connectivity checks
```

`AIService.generate(task, context)`:
1. Mock mode: return mock text.
2. Live mode: for each configured provider, up to two attempts. The output must parse into the task's schema, must not
   contain a figure of four or more digits that is absent from the evidence, and must not use approval language.
3. Otherwise return mock text flagged `fallback: true`, and log why.

A failed call changes nothing in the case. SDKs are imported lazily, so mock mode does not need them at runtime.

## Frontend

- `App.tsx` routes: `/`, `/borrower/intake`, `/case/:caseId/{investigation,diagnosis,restructure,options,proposal,tracking}`,
  `/advisor`, `/demo-control`.
- `case/CaseLayout.tsx` loads the case once and shares it with the six stage pages through the router outlet; the
  stage navigation reflects `stages` from the backend, so locked steps come from server state.
- All state lives on the server. Refreshing any page reloads it from the API. Only an unsaved onboarding draft is kept
  in the browser.
- The restructuring page sends every change to the backend for recalculation; it does no loan arithmetic.
- Design tokens are in `index.css` and follow the UI/UX blueprint (ink #163247, teal #11766F, canvas #F4F7F8).
  Status is always text plus a shape, never colour alone.

## Main API contracts

| Area | Routes |
|---|---|
| Borrowers | `POST/GET/PUT /api/borrowers[/{id}]` |
| Cases | `POST /api/cases`, `GET /api/cases/{id}`, `POST .../consents`, `POST .../escalate` |
| Documents | `GET/POST /api/cases/{id}/documents`, `POST .../documents/synthetic`, `GET /api/documents/{id}/file` |
| Investigation | `POST .../investigation/run`, `GET .../investigation`, `POST .../clarifications/{id}`, `POST .../findings/{id}/feedback`, `POST .../investigation/explain` |
| Calculations | `POST /api/calculations/emi` |
| Restructuring | `GET/PUT /api/cases/{id}/restructure`, `POST .../restructure/preview` |
| Lenders | `GET /api/lenders`, `PUT /api/lenders/{id}` |
| Recommendations | `GET .../recommendations?priority=`, `POST .../recommendations/explain`, `POST .../selection` |
| Proposal | `GET .../proposal`, `POST .../proposal/checkpoints`, `GET .../proposal/pdf` |
| Application | `GET .../application`, `POST .../application/{submit,advance}`, `POST .../application/queries/{id}/{draft,respond}` |
| Advisor | `GET /api/advisor/cases[/{id}]`, `POST .../actions`, `GET/POST /api/knowledge`, `POST /api/knowledge/{id}/review` |
| AI | `GET /api/ai/status`, `POST /api/ai/check`, `PUT /api/ai/mode`, `POST /api/ai/{transcribe,translate,speak}` |
| Demo | `POST /api/demo/{reset,load,trigger}`, `POST /api/demo/regenerate-documents/{case}`, `GET /api/demo/{scenarios,state,logs}`, `GET /api/demo/ground-truth/{case}` |

Interactive documentation with every schema: http://127.0.0.1:8000/docs.

## Privacy and safety choices

- Provider keys are backend-only and never reach the browser.
- Uploads: PDF only, 10 MB limit, magic-number check, sanitised filename, stored under the app's file directory;
  files are served only by document ID through the API.
- Consent is asked at the point of need: analysing documents, using payment data, sharing with a lender.
- Sensitive actions write audit events: consents, uploads, answers, selections, submissions, escalations, advisor
  actions, policy edits, mode changes, resets.
- The advisor routes require a role header. This is a placeholder for sign-in, not access control.
