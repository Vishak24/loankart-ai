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
| **Implemented** (runs offline, covered by tests) | Advisor sign-in and per-borrower access control, rate limiting, hardened uploads; onboarding; PDF generation, extraction and analysis; investigation and findings; calculation engine; restructuring levers; lender simulator and ranking; proposal PDF; advisor workspace; SQLite persistence; demo control |
| **Simulated** (clearly labelled in the UI) | All lenders, lender rules, decisions, queries and offers; the Paytm merchant data (a synthetic fixture); application events; the document pack for self-onboarded borrowers |
| **Integration code written, awaiting credentials** | Claude explanations; Sarvam chat, translation, speech and Vision OCR; Paytm Settlement Summary request. Each was only exercised with invalid keys (it returned the provider's authentication error). **No successful live call has been made**, so treat live mode as untested. The Paytm request is not wired into cases |
| **Planned, not built** | Individual accounts, MFA and a shared session store; real lender/NBFC or Account Aggregator integrations; credit-bureau data; a Tamil interface; a durable job queue; a production database; hosted deployment |

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

**Advisor and demo-control pages ask for a passcode.** Set `LOANKART_ADVISOR_PASSWORD` in `backend/.env` (and `LOANKART_SECRET_KEY`
so sessions survive restarts). The easy way: from `backend/`, run `python scripts/set_advisor_password.py`. It asks twice with hidden input, writes both settings to `backend/.env` (mode 600) and prints neither. Until a passcode is set, advisor sign-in stays closed; no passcode is ever generated or shown, and credentials never appear in logs.
The borrower demo (landing page → "Open the demo case") needs no sign-in.

## Test

```bash
cd backend && .venv/bin/pytest -q            # 159 tests: engines, API, journey run twice from reset, security
cd frontend && npm test                      # 11 unit tests
cd frontend && npm run build                 # type-check + production build
# 33-step journey through the dev proxy. It RESETS demo data: run it against a throw-away backend (temp DB, own ports).
cd frontend && LOANKART_ADVISOR_PASSWORD=<the backend's passcode> npm run check:journey -- http://127.0.0.1:<frontend port>
```

Tests use a temporary database, force mock mode and blank any real API keys. Details and known gaps: [TESTING.md](TESTING.md).

## Demo walkthrough

Landing → "My loan was rejected" → use the synthetic demo borrower → load the document pack → give permission → run the
investigation → review findings and answer three questions → test a smaller amount, a longer tenure and closing the
costly loan → compare ranked options → select the gold-backed overdraft → confirm the proposal checkpoints → submit
the simulated application → answer two lender queries → simulated offer → ask an advisor → resolve in the advisor
workspace → reset from the demo control centre. Step-by-step script (about six minutes): [DEMO_GUIDE.md](DEMO_GUIDE.md).

## Security and limitations

Full detail, configuration and deployment checklist: **[SECURITY.md](SECURITY.md)**.

**Implemented** (each has automated tests in `backend/tests/test_security.py`)
- **Advisor sign-in** with a passcode and a signed, expiring, `HttpOnly` session cookie. The old client-set role header is gone and grants nothing.
- **Per-borrower authorisation.** A browser can only open the profile, case and documents it created; every case, document and borrower route checks this, and a test fails if any non-public route answers an anonymous request.
- **AI endpoints** need a session (advisor-only for connectivity checks and mode changes) and are **rate limited** per client and by a daily server-wide ceiling, so provider spend is capped rather than unbounded. (The ceiling counts requests, not provider calls, and a determined visitor can exhaust it for everyone.) Login, uploads and profile creation have their own limits.
- **Demo reset and scenario tools** are advisor-only, and absent (404) in production unless explicitly enabled.
- **Production mode** (`LOANKART_ENV=production`) refuses to start without a signing key, an advisor passcode and exact `https://` CORS origins, hides the API docs and sets `Secure` cookies and HSTS.
- **Upload hardening:** PDF structure checks, 10 MB / 25-page / 20-per-case caps, refusal of scripts, attachments and encrypted files, and parsing in an isolated process with a timeout, resource limits and no API keys in its environment.
- Request-size limits, CSRF origin check, explicit CORS, security headers, generic error messages, parameterised SQL, keys server-side only, and a commit hook that blocks secrets in `.env.example`.

**Still not production-ready**
- **One shared advisor passcode**: no individual accounts, MFA or per-person audit trail.
- Sessions are stateless cookies and cannot be revoked before they expire; a borrower who loses their browser session loses access to their case.
- Rate limits and the investigation job are in process memory: run a single backend process.
- No encryption at rest, retention policy or consent ledger. **Do not load real borrower data.**
- Upload scanning is heuristic and the parser is isolated at process level, not in a container.
- No independent security review or penetration test.
- Live provider calls (Claude, Sarvam, Paytm) have not been exercised end to end.

Run it on `127.0.0.1` for demos. To expose it anywhere else, follow the deployment checklist in SECURITY.md.

## Future roadmap

1. Individual advisor accounts (OIDC) with MFA and a per-person audit trail, borrower sign-in with recovery, and server-side session revocation.
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
