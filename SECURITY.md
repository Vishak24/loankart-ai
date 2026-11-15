# Security

LoanKart.ai is a **hackathon prototype**. It has been hardened for a *supervised, small-scale deployment of synthetic
data*; it has **not** been independently audited and must not hold real borrower data. This page lists what is
implemented, how to configure it, and what is still missing. Nothing here is a claim of production readiness.

## Model in one paragraph

Two kinds of signed, expiring, `HttpOnly` cookie sessions. A **borrower session** is granted when a borrower profile is
created (or the shared synthetic demo case is opened) and covers only that borrower's profile, case and documents. An
**advisor session** is granted by one shared passcode and covers every case plus the advisor and demo-control routes.
Identifiers are never treated as secrets: access is checked against the session on every case, document and borrower
route. Nothing honours the old `X-LoanKart-Role` header any more.

## Controls implemented

| Area | Control | Where |
|---|---|---|
| Advisor authentication | Passcode checked with a constant-time comparison; session is an HMAC-signed, expiring (default 4 h) `HttpOnly`, `SameSite=Lax` cookie, `Secure` in production; sign-in is rate limited (5/min/client); failed and successful sign-ins are audit-logged | `security.py`, `routes.py` |
| Borrower authorisation | Every `/cases/{id}/…`, `/documents/{id}/file` and `/borrowers/{id}` route checks session ownership; "missing" and "not yours" give the same 403 so IDs cannot be probed; a test walks the whole OpenAPI route table and fails if any non-public route answers an anonymous request with anything but 401 | `security.py`, `tests/test_security.py` |
| AI endpoints | `translate`, `speak`, `status` need a session; `check`, `mode`, `transcribe` and the knowledge routes are advisor-only; every route that can spend provider credits is rate limited per client (20/min) and by a whole-server daily ceiling (500/day). This **caps** spend; it does not prevent it (see limitations) | `routes.py` |
| Demo control | Reset, scenario loading, regenerate, trigger, state, logs and ground-truth are advisor-only, and **do not exist (404) in production** unless `LOANKART_ENABLE_DEMO_TOOLS=1`. The shared demo case a visitor can open is off in production unless `LOANKART_PUBLIC_DEMO=1` | `security.require_demo_admin` |
| Rate limiting | In-memory sliding windows: 600 req/min/client overall, plus login, AI, upload and profile-creation buckets; `429` with `Retry-After`; client address from the socket, or from the last `X-Forwarded-For` entry only when `LOANKART_TRUST_PROXY=1` | `security.RateLimiter` |
| Uploads | `.pdf` only; `%PDF-` header and `%%EOF` trailer; 10 MB cap enforced from `Content-Length` before the body is parsed; refuses PDFs containing `/JavaScript`, `/Launch`, `/EmbeddedFile`, `/RichMedia`, `/SubmitForm`, `/ImportData` or `/Encrypt`; 25-page cap; at most 20 uploads per case; sanitised filename and a resolved-path check when serving; refused files are deleted | `extraction.py`, `environment.py` |
| PDF processing | Uploaded PDFs are parsed in a separate throw-away process: 20 s timeout, CPU/file-size/memory limits where the OS enforces them, and an empty environment (so no API keys are inherited) | `extraction_worker.py` |
| Request limits | Bodies over 1 MB (JSON) are refused with 413 before parsing; chunked bodies without a length are refused (411); large bodies without a session are refused unread | `security.http_guard` |
| CSRF | `SameSite=Lax` cookies, plus writes carrying an `Origin` outside `LOANKART_CORS_ORIGINS` (and not the server's own host) are refused | `security.http_guard` |
| CORS | Explicit origin list, never `*`; credentials allowed only for those origins; only `Content-Type` is an allowed request header | `main.py` |
| Production start-up | `LOANKART_ENV=production` **refuses to start** unless the signing key (32+ chars) and advisor passcode (12+) are set and CORS lists exact `https://` origins; unknown `LOANKART_ENV` values are an error; `/docs`, `/redoc` and `/openapi.json` are off | `config.production_problems` |
| Errors and headers | Unexpected errors return a generic message (details only in the advisor-only log); `nosniff`, `X-Frame-Options: DENY`, `Referrer-Policy: no-referrer`, `Cache-Control: no-store` and a restrictive CSP on API JSON; HSTS in production | `security.http_guard` |
| Secrets | Keys are read by the backend only and never sent to the browser; `.env*` is git-ignored; a tracked pre-commit hook blocks a real value in any `.env.example` and runs gitleaks | `.githooks/pre-commit` |
| Dependencies | `npm audit` clean; `pip-audit` clean after pinning `fastapi 0.163.0`, `starlette 1.10.0`, `pytest 9.2.0` | `requirements.txt` |

Enable the hook once per clone: `git config core.hooksPath .githooks` (needs [gitleaks](https://github.com/gitleaks/gitleaks) for the second check).

## Configuration

| Variable | Development (default) | Production |
|---|---|---|
| `LOANKART_ENV` | `development` | `production` |
| `LOANKART_SECRET_KEY` | optional (random per run) | **required**, 32+ random characters |
| `LOANKART_ADVISOR_PASSWORD` | optional (a random passcode is printed at start-up; set it in `backend/.env` to keep it) | **required**, 12+ characters |
| `LOANKART_CORS_ORIGINS` | `http://localhost:5173,http://127.0.0.1:5173` | **required**, exact `https://` origin(s) |
| `LOANKART_PUBLIC_DEMO` | on | off unless set to `1` |
| `LOANKART_ENABLE_DEMO_TOOLS` | on (advisor-only) | off unless set to `1` (advisor-only) |
| `LOANKART_TRUST_PROXY` | off | `1` only behind your own reverse proxy |
| `LOANKART_RATE_*`, `*_SESSION_HOURS` | defaults in `backend/.env.example` | tune per deployment |

## Deployment checklist (not done by this repository)

1. Serve the frontend and `/api` from **one site** over HTTPS (reverse proxy). Cookies are `SameSite=Lax`, so a front end on a different site will not stay signed in.
2. Set the production variables above; never put values in `.env.example`.
3. Put the proxy's own request-size and rate limits in front, and set `LOANKART_TRUST_PROXY=1` there only.
4. Run **one** backend process: rate-limit counters and the investigation job live in process memory.
5. Rotate any provider key that has ever sat in a file other than `backend/.env`.

## Known limitations (read before trusting this)

- **One shared advisor passcode.** No per-person accounts, no password hashing store, no MFA, no lockout beyond rate limiting, no individual accountability in the audit trail. Anyone with the passcode is every advisor.
- **Sessions are stateless signed cookies.** They cannot be revoked server-side before they expire (4 h advisor, 12 h borrower); rotating `LOANKART_SECRET_KEY` invalidates all of them.
- **Borrower access is possession of a browser session.** Clear cookies or switch device and the borrower loses access to their case; there is no recovery flow and no borrower sign-in.
- **The shared demo case is shared.** When `LOANKART_PUBLIC_DEMO=1`, every visitor works on the same synthetic case and can change it for the others.
- **Spend is capped, not prevented.** Anyone can create a borrower session, so the AI limits bound cost rather than stop it, and one client can use up the whole-server daily ceiling for everyone. The ceiling counts HTTP requests, not provider calls: one request can retry across providers, and a live investigation with Sarvam Vision calls it once per document.
- **Rate limits are per process and per address.** They reset on restart, do not span several workers, and clients behind one NAT share a bucket.
- **Upload scanning is heuristic.** The active-content check reads raw bytes (names can be obfuscated); isolation of the parser is process-level, not a container: the worker runs as the same OS user and could read `backend/.env` if the parser were exploited, `RLIMIT_AS` is not enforced on macOS, and its output is size-checked only after it has been buffered. The 25-page cap is a constant (`MAX_PDF_PAGES`) that a long real statement can exceed.
- **No encryption at rest, no retention policy, no consent ledger.** SQLite and PDFs are plain files. Do not load real personal or financial data.
- **No audit-grade logging**: logs live in the same SQLite file and are cleared by a demo reset.
- **Provider calls remain untested live** (see `TESTING.md`); the credit ceilings above were exercised in mock mode only.
- **No external penetration test or dependency-supply-chain review** has been done.
