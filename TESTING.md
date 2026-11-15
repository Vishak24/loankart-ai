# Testing

## Commands

```bash
cd backend && .venv/bin/pytest -q            # backend: 159 tests, about 55 seconds
cd frontend && npm test                      # frontend unit tests: 11
cd frontend && npm run build                 # TypeScript type-check and production build
cd frontend && LOANKART_ADVISOR_PASSWORD=... npm run check:journey -- <frontend url>   # integration: 33 steps through the Vite proxy
cd frontend && npm run gen:types             # regenerate TypeScript types from the backend's OpenAPI contract
```

`check:journey` **resets demo data** before and after it runs and signs in as an advisor, so run it against a throw-away backend
(temporary `LOANKART_DB_PATH`, its own ports, a test passcode), never one holding data you want to keep. It keeps a borrower
cookie jar and an advisor cookie jar, because the sessions are `HttpOnly` cookies.

## Backend tests (`backend/tests/`)

| File | Tests | Covers |
|---|---|---|
| `test_calculations.py` | 33 | EMI, amortisation, total interest, FOIR, DSCR, LTV, APR, cash flow, amount and tenure changes, refinancing; invalid inputs, boundaries, rounding. Expected values were worked out independently of the code under test |
| `test_engines.py` | 47 | Layer separation (investigation code cannot import the ground truth); dataset coherence for all six scenarios; PDFs are real and regenerate byte-identically; every transaction survives the PDF round trip; analysis reproduces ground truth from documents alone; finding structure and wording; all nine lender decisions reachable; ranking determinism; recovery plan; Sarvam Vision output (Markdown or HTML) reaching the parser |
| `test_api.py` | 19 | Milestone-1 borrower API: validation, persistence, CORS |
| `test_journey.py` | 2 | The 17 acceptance steps through the API in mock mode, run twice from reset with identical results; reset restores the initial state |
| `test_security.py` | 36 | Sessions and forged/expired/tampered cookies; every route requires a session unless on the public list (walks the OpenAPI table); the old role header grants nothing; borrower isolation across profile, case and document; borrower-only journey; rate limits (login, AI per client and daily, upload, create, default, forwarded-header handling); upload hardening (scripts, attachments, encryption, truncation, page cap, timeout, per-case cap, refused files deleted); body-size and chunked-body refusal; CSRF origin check; CORS; generic errors and headers; production mode (refuses unsafe start-up, hides docs, secure cookies, demo tools and shared demo off, still isolates borrowers). The suite was mutation-checked: removing a guard, a limit, the ownership check or the PDF scan each makes it fail |
| `test_secrets.py` | 19 | Advisor passcode, signing key, provider keys, cookies and auth headers never reach captured logs, stdout/stderr or stored events; no passcode is generated when none is set and sign-in stays closed; a real uvicorn process logs the three auth events and no secret; log scrubbing keeps the record shape uvicorn needs, covers non-string messages, and every stored event is scrubbed (a key cut by truncation cannot survive); Claude and Sarvam error text and AI-service events and status rows never carry the key; mock mode (and live without keys) works with no credentials; `.env.example` holds no values; no credential-shaped strings in tracked files or frontend source; the password script writes mode 600, prints nothing secret, keeps an existing key and rejects weak entries. Mutation-checked: disabling `redact()` fails the log, provider and event tests |
| `test_workflow_api.py` | 22 | 404/409/422 handling, upload validation and safe storage, persistence across restarts, upgrade of a milestone-1 database, a custom borrower's journey, rejection and human-review paths, Paytm consent, provider failure handling, permissions, knowledge kept apart from policy, concurrent requests, exact ground-truth comparison after a correction, refresh after answers are edited, the approval-language filter |

Tests use a temporary database and file store, force mock mode, set a test signing key and passcode, and blank out any real API keys. The default `client` fixture is signed in as an advisor; borrower-only and anonymous behaviour is tested with separate clients.

The sign-in gate and the borrower demo were also clicked through in a real browser (Chrome, mock mode, throw-away ports) after the security changes: wrong-passcode refusal, sign-in, session surviving reload, sign-out, and "Open the demo case" as a visitor with 48 documents loaded.

## Frontend tests

- `src/format.test.ts`: rupee formatting, missing values shown as missing, signed changes.
- `src/onboarding/steps.test.ts`: conditional questions, payload building, "I'm not sure" sent as unknown, validation.
- `scripts/check-journey.mjs`: every endpoint the pages call, through the dev proxy, checking the fields the pages read.
- TypeScript types are generated from the backend contract, so a contract change that breaks a page fails `npm run build`.

## Browser verification (15 November 2026)

Not an automated suite. I drove a real Chromium browser with a script that clicks and types by dispatching DOM events,
against the running dev servers in mock mode, and looked at screenshots of each page. Real mouse and keyboard input
was not used. An error listener was attached after each page had loaded, so an error thrown during the first render
of a page would have been missed by it.

- Full journey: landing → onboarding with the demo borrower → documents → consent → investigation (task states seen
  changing live) → diagnosis, AI summary, three questions answered → restructuring with live recalculation → options,
  priority change, three-way comparison → proposal, PDF, checkpoints → submission → two queries drafted and answered →
  simulated offer → escalation.
- Advisor: queue, case review, accepting a finding, resolving, knowledge capture and approval, lender catalogue.
- Demo control: ground-truth comparison, three forced lender events, mode switch, connectivity check, loading an
  alternate borrower, reset.
- Fresh onboarding filled in field by field (scripted), including validation, "Why we ask" and "I'm not sure".
- Responsive: 14 pages at 375, 390, 768, 1024 and 1440 px (70 combinations), all collapsible sections opened. No
  horizontal page scrolling in any of them.
- No console errors were captured during these runs (see the caveat above).
- One bug was found this way and fixed: parallel requests from the browser broke database connections. A test now
  covers it.

## Known limitations

**Not tested**
- Live AI output. On 15 Nov 2026 one authentication call each succeeded with real keys (Claude: a token-free
  model lookup; Sarvam: a 5-token chat). Nothing beyond authentication has been exercised: no live explanation,
  summary, proposal draft, translation, speech or Vision output, and no Paytm call (no Paytm credentials set).
  Earlier, every adapter call was also sent with an invalid key and returned that provider's authentication error, which shows the requests are
  well-formed. That check found and fixed one bug (the Sarvam Vision
  call used a parameter the installed SDK does not accept).
- Voice recording in a browser (needs a microphone), the "Read in Tamil" result in live mode, and Sarvam Vision.
- Editing lender rules, the advisor value-correction form and the upload button were exercised through the API tests,
  not clicked in the browser.
- Safari and Firefox. Screen readers. Keyboard-only navigation was not walked through.
- There are no automated browser tests; the browser checks above were manual.

**By design in this prototype**
- Advisor access is one shared passcode and a signed cookie (see SECURITY.md for what that does not give you).
- The baseline parser reads the layouts this project generates. An arbitrary real bank PDF is stored and marked "not
  recognised" unless Sarvam Vision is enabled, and that path is untested.
- Borrowers who onboard themselves get a synthetic document pack built around their answers, not their real documents.
- The investigation runs as an in-process background task. A backend restart mid-run leaves it "running"; press
  **Run again**.
- New case pages have their English text inline. Only landing and onboarding text is in `i18n/en.ts`. There is no
  Tamil interface.
- Onboarding does not collect the rejecting lender's name or the rejection date; the synthetic rejection letter
  supplies them.
- The refinance lever uses an illustrative rate and tenure, not an evaluated lender product.
- Bureau scores are not modelled.
- Chat streaming and tool calling are not used: every AI task is a single structured request.
- The Paytm Settlement Summary request is implemented but not connected to cases; the Paytm MCP server is not called.
