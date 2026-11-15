# LoanKart.ai

**AI-powered financial investigation, restructuring and lending intelligence platform for self-employed borrowers and small businesses.**

> **Hackathon prototype. Not production software.** Every borrower, lender, document and figure in this repository is
> synthetic. Lender decisions come from a simulator with fictional rules. Nothing here is a real offer, sanction or
> financial advice. There is no real sign-in. See [Security and limitations](#security-and-limitations) before deploying anything.

## Problem

A self-employed borrower in India (a textile wholesaler, a kirana owner, a contractor) gets a loan rejected with a
one-line letter. They do not learn *why*, whether their own figures or their documents are the problem, or what
to change. Their income is spread across bank statements, GST returns, ITRs and payment-app settlements that do not
agree with each other, and a human advisor cannot review every case.

## Solution

LoanKart.ai is not a lender and not a chatbot. It is an evidence-first workspace:

**Understand the rejection → improve the numbers → find a more suitable financing route.**

It reads the borrower's documents, reconciles them, lists evidence-linked findings ("a possible factor", never "the
reason"), models eight restructuring levers with before/after figures, tests the result against a lender simulator and
hands the borrower a draft proposal. AI writes explanations only. **Calculations, lender rules and rankings are
deterministic code**, and AI output is rejected if it mentions a figure that is not in the evidence.

## Key features

1. Guided onboarding, one question at a time, with "Why we ask" and "I'm not sure".
2. A synthetic document pack generated as real PDFs (bank statements, GST returns, ITRs, loan statements, financials, rejection letter).
3. An investigation that parses those PDFs, classifies transactions, reconciles sources and produces evidence-linked findings, with live task states.
4. Borrower confirmation of anything uncertain before it is counted.
5. Eight restructuring levers (amount, tenure, existing loans, security, loan type, evidence, ...) with exact recalculation (`Decimal` engine).
6. Evaluation against 8 fictional lenders (16 products) and a ranking whose weights are disclosed and change with the borrower's priority.
7. A draft proposal PDF, a simulated application with lender queries and outcomes, and escalation to a human advisor.
8. An advisor workspace: corrections, audit trail and expert-approved knowledge capture (kept apart from lender policy).
9. A demo control centre: provider connectivity checks, forced lender events, ground-truth comparison and one-click reset.

### What is real, simulated, waiting for credentials, or planned

| Status | What |
|---|---|
| **Implemented** (runs offline, covered by tests) | Onboarding; PDF generation, extraction and analysis; investigation and findings; calculation engine; restructuring levers; lender simulator and ranking; proposal PDF; advisor workspace; SQLite persistence; demo control |
| **Simulated** (clearly labelled in the UI) | All lenders, lender rules, decisions, queries and offers; the Paytm merchant data (a synthetic fixture); application events; the document pack for self-onboarded borrowers |
| **Integration code written, awaiting credentials** | Claude explanations; Sarvam chat, translation, speech and Vision OCR; Paytm Settlement Summary request. Each was only exercised with invalid keys (it returned the provider's authentication error). **No successful live call has been made**, so treat live mode as untested. The Paytm request is not wired into cases |
| **Planned, not built** | Real authentication and authorisation; real lender/NBFC or Account Aggregator integrations; credit-bureau data; a Tamil interface; a durable job queue; a production database; hosted deployment |

LoanKart.ai has **no production Paytm integration and no live bank or NBFC integration**.

## Architecture

```
 Browser (React 19 + Vite)
        │  /api  (dev proxy)
        ▼
 FastAPI routes (thin) ─► workflow / investigation / restructuring / recommendations   deterministic
        │                         │                       │
        │                  analysis + extraction     calculations (Decimal) + lender simulator
        ▼                         ▼
   SQLite (case state as JSON)   PDFs on disk (pdfplumber to read, reportlab to write)
        │
        └─► AIService ─► mock provider (default) │ Claude │ Sarvam      explanations only, schema- and evidence-checked
```

Details: [ARCHITECTURE.md](ARCHITECTURE.md).

## Technology stack

| Layer | Technology |
|---|---|
| Frontend | React 19, Vite 6, TypeScript, Tailwind CSS 4, React Router 7 |
| Backend | Python 3.11, FastAPI, Pydantic 2, Uvicorn |
| Database | SQLite (file), JSON columns for case state |
| Documents | reportlab (PDF generation), pdfplumber (PDF text extraction) |
| AI (optional) | Anthropic SDK (Claude), Sarvam AI SDK; a built-in mock provider is the default |

## Setup

Requires Python 3.11+, Node 20+ and [uv](https://docs.astral.sh/uv/) (or `python -m venv` and `pip`).

```bash
git clone https://github.com/<your-account>/loankart-ai.git && cd loankart-ai

# Backend
cd backend
uv venv .venv && uv pip install -p .venv/bin/python -r requirements.txt

# Frontend
cd ../frontend
npm install
```

## Environment configuration

The app needs **no configuration** for the demo: with no keys it runs fully in mock mode with no internet
(web fonts fall back to system fonts).

For live AI, copy the template and fill in only what you have:

```bash
cp backend/.env.example backend/.env      # backend/.env is git-ignored
```

| Variable | Purpose |
|---|---|
| `ANTHROPIC_API_KEY`, `ANTHROPIC_MODEL` | Claude explanations |
| `SARVAM_API_KEY` and `SARVAM_*_MODEL` | Sarvam chat, translation, speech, Vision |
| `LOANKART_AI_MODE` | `mock` (default) or `live` |
| `LOANKART_CORS_ORIGINS` | Browser origins allowed to call the API |
| `PAYTM_*` | Optional connectivity check only |

Keys are read by the backend only and never sent to the browser; the frontend's only `VITE_` variables are URLs.
**Never put real values in `.env.example`.** Full guide: [API_SETUP.md](API_SETUP.md).

## Run

```bash
# Terminal 1: backend on http://127.0.0.1:8000  (API docs at /docs)
cd backend && .venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000

# Terminal 2: frontend on http://127.0.0.1:5173  (proxies /api and /health to the backend)
cd frontend && npm run dev -- --host 127.0.0.1
```

Open http://127.0.0.1:5173. Keep the backend on `127.0.0.1`; see the security notes before binding it elsewhere.

## Test

```bash
cd backend && .venv/bin/pytest -q            # 123 tests: engines, API, full journey run twice from reset
cd frontend && npm test                      # 11 unit tests
cd frontend && npm run build                 # type-check + production build
cd frontend && npm run check:journey         # 32-step journey through the dev proxy; both servers must be running
```

Tests use a temporary database, force mock mode and blank any real API keys. Details and known gaps: [TESTING.md](TESTING.md).

## Demo walkthrough

Landing → "My loan was rejected" → use the synthetic demo borrower → load the document pack → give permission → run the
investigation → review findings and answer three questions → test a smaller amount, a longer tenure and closing the
costly loan → compare ranked options → select the gold-backed overdraft → confirm the proposal checkpoints → submit
the simulated application → answer two lender queries → simulated offer → ask an advisor → resolve in the advisor
workspace → reset from the demo control centre. Step-by-step script (about six minutes): [DEMO_GUIDE.md](DEMO_GUIDE.md).

## Security and limitations

**In place**
- API keys live only in `backend/.env` / the backend environment; `.env*` is git-ignored; `/api/ai/status` never returns key values.
- Uploads accept only `.pdf` files with a `%PDF` header up to 10 MB, are stored under a sanitised name and served only from the app's own storage directory.
- All SQL is parameterised (the only interpolated identifiers are fixed table names).
- CORS is an explicit allow-list (no wildcard); unexpected errors return a generic message and are logged server-side.
- Dependencies were audited (`npm audit`, `pip-audit`) before publishing; see the pinned versions in `backend/requirements.txt`.

**Not production-ready. Known limitations**
- **No authentication.** Anyone who can reach the API can read any case by ID. The advisor area is guarded only by a
  client-supplied `X-LoanKart-Role` header, which any caller can set: **that is not access control**.
- **Demo and AI endpoints are open.** `/api/demo/*` (including reset, which wipes the database) and `/api/ai/*`
  (which can spend Anthropic/Sarvam credits in live mode) require no sign-in, and there is no rate limiting.
  Run it on `127.0.0.1` only, and do not expose it with live keys configured.
- Real borrower data must not be used: there is no encryption at rest, consent ledger, retention policy or audit-grade logging.
- PDF parsing runs in-process on uploaded files with no sandbox or page limit.
- The investigation runs as an in-process background task and does not survive a restart mid-run.
- Live provider calls have not been exercised end to end (see the table above).

Before any real use you need, at minimum: real authentication and per-case authorisation, closing or protecting the
demo and AI endpoints, rate limiting, TLS and a proper database.

## Future roadmap

1. Real sign-in (OIDC), role-based access and per-case authorisation; remove the role header.
2. Account Aggregator and GST/bureau data in place of synthetic documents, with a consent ledger.
3. Real lender and NBFC integrations behind the existing simulator interface.
4. Wire Paytm settlement data into cases once credentials are available and validated.
5. Tamil (and other Indian-language) interface and voice flows; durable job queue; PostgreSQL; hosted deployment.

## Layout

```
backend/app/
  main.py            app start-up, CORS, central error mapping
  routes.py          every HTTP route (thin)
  schemas.py         Pydantic contracts: the single source for the frontend's TypeScript types
  config.py db.py    settings; SQLite schema and row access
  calculations.py    deterministic financial engine (Decimal)
  synthetic.py       ground-truth datasets and the scenario library
  docgen.py          PDF document factory
  extraction.py      PDF text to structured fields and rows
  analysis.py        classification, reconciliation, findings
  investigation.py   task orchestration with persisted task states
  lenders.py         lender catalogue loader and decision simulator (data/lenders.json)
  restructuring.py   the eight restructuring dimensions
  recommendations.py disclosed ranking
  workflow.py        proposal, simulated application, escalation
  advisors.py        advisor queue, actions, knowledge
  environment.py     scenario cases, document packs, seed, reset, ground-truth comparison
  integrations/      provider interfaces, mock, Claude, Sarvam, Paytm, AI service
backend/tests/       pytest suite
frontend/src/        api/ components/ pages/ case/ onboarding/ i18n/
```
