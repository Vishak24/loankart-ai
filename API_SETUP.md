# API setup

The app is complete without any of this. Add keys only when you want live AI.

## Where the keys go

One file: **`backend/.env`**. Create it by copying the example:

```bash
cd backend
cp .env.example .env
```

Then edit `backend/.env`:

| What | Line to fill in |
|---|---|
| Anthropic (Claude) API key | `ANTHROPIC_API_KEY=sk-ant-...` |
| Sarvam AI API key | `SARVAM_API_KEY=...` |
| Paytm merchant ID and key (optional, not used for live calls yet) | `PAYTM_MERCHANT_ID=`, `PAYTM_MERCHANT_KEY=`, `PAYTM_ENVIRONMENT=staging` |

Restart the backend after editing (`--reload` does not re-read `.env`). Keys exported in your shell override the file.

## Model names

Set in the same file. Defaults are already filled in.

| Variable | Default | Notes |
|---|---|---|
| `ANTHROPIC_MODEL` | `claude-opus-5-5` | Any current Claude model ID, written exactly, with no date suffix |
| `SARVAM_CHAT_MODEL` | `sarvam-105b` | |
| `SARVAM_STT_MODEL` | `saaras:v4` | `saaras:v3` also documented |
| `SARVAM_TTS_MODEL` | `bulbul:v4-flash` | `bulbul:v3` also documented |
| `SARVAM_TRANSLATE_MODEL` | `sarvam-translate:v1` | |
| `LOANKART_USE_SARVAM_VISION` | `0` | `1` uses Sarvam Vision (Document AI parse) to read documents in live mode |

Sarvam model IDs and SDK calls were taken from docs.sarvam.ai on 15 November 2026 and checked against the installed
`sarvamai` 0.1.46 package. Sarvam Vision is reached through the Document AI parse API and needs no model name, so
there is no `SARVAM_VISION_MODEL` variable.

## Switching between mock and live

- At start-up: `LOANKART_AI_MODE=mock` or `live` in `backend/.env`.
- While running: open `/demo-control` and use **Mock (no external calls)** or **Live AI**. The choice is stored in the database
  and survives restarts. **Reset all demo data** returns it to the start-up default.
- `LOANKART_REASONING_PROVIDER=claude` (default) or `sarvam` chooses which provider writes explanations. Each configured
  provider gets two attempts, the preferred one first; if all fail, the built-in mock text is used and marked as a fallback.

If Live AI is selected with no key configured, the page says so and mock responses are used.

## Testing each connection

On `/demo-control`, press **Check provider connectivity**. It makes one real, minimal call per configured provider
and shows the result beside each one:

| Provider | Check performed |
|---|---|
| Claude | Looks up the configured model (no tokens spent) |
| Sarvam chat | A five-token completion |
| Sarvam translate | Translates "Hello" to Tamil |
| Sarvam speech, Sarvam Vision | No cheap check exists; they are exercised on first use and errors appear under Logs |
| Paytm | One Settlement Summary request, if the three Paytm values are set |

Or from a terminal: `curl -X POST http://127.0.0.1:8000/api/ai/check`.

To see live output in the product: Diagnosis → **Explain the findings**; Options → **Explain why this is first**;
Tracking → **Draft a reply from my documents**; Advisor → Knowledge review → **Structure as a candidate** or the voice
note button.

## What each provider is used for

| Provider | Used for | Never used for |
|---|---|---|
| Claude | Finding explanations, ranking commentary, proposal summary, query drafts, escalation summaries, structuring advisor notes | Calculations, lender rules, lender decisions, ranking |
| Sarvam chat | The same reasoning tasks, as the alternative or second-choice provider | Same as above |
| Sarvam translate | "Read in Tamil" on the diagnosis summary | |
| Sarvam speech | Advisor voice notes (Saaras). A Bulbul text-to-speech endpoint exists at `POST /api/ai/speak` but has no button yet | |
| Sarvam Vision | Optional OCR text source for documents | |

Every AI output is validated against a schema, checked so that it mentions no figure absent from the evidence it was
given, and rejected if it uses approval language for simulated results.

## Paytm

Checked on 15 November 2026 against paytmpayments.com/docs and github.com/paytm/paytm-agent-skills.

| Paytm offering | What it is | How LoanKart relates to it |
|---|---|---|
| Payment Gateway APIs | Checkout, payment links, QR, refunds, subscriptions | Not used: LoanKart takes no payments |
| Settlement APIs | Settlement Summary, Detail, Order Detail and Transaction Detail | The Settlement Summary request is implemented in `backend/app/integrations/paytm.py`. It is not wired into cases yet |
| Paytm MCP Server (beta), `https://mcp.paytmpayments.com/mcp` | Lets an AI assistant call Paytm APIs after the merchant signs in to their Paytm dashboard. Tools include `fetch_settlement_orders` and `fetch_settlements_by_date` | Not called by the backend. A merchant can connect it to their own assistant |
| Paytm Agent Skills | A skills bundle that teaches coding assistants the Payment Gateway integration | Development aid only |

None of these is a lending or underwriting API, and LoanKart does not present payment data as one.

**What the product uses today:** a clearly labelled synthetic Paytm merchant fixture, as supplementary cash-flow
evidence, only after the borrower gives a specific consent. Paytm collections are never treated as total revenue.

**Where Paytm credentials go:** `backend/.env`.

| Variable | Purpose |
|---|---|
| `PAYTM_MERCHANT_ID` | The merchant's MID |
| `PAYTM_CLIENT_ID`, `PAYTM_ACCESS_TOKEN` | Client ID and JWT for the settlement APIs, issued by Paytm for that merchant |
| `PAYTM_MERCHANT_KEY`, `PAYTM_ENVIRONMENT` | Payment Gateway key and environment. Read but unused |

With the first three set, **Check provider connectivity** sends one Settlement Summary request. Paytm documents that
API as production only, with at most one week per call and six months of history. The request has been sent to
Paytm's endpoint with invalid credentials only (it returned an authentication error); a successful response has never
been seen, so turning real settlements into the evidence summary is still to be done. Use it only with the merchant's
authorisation.

## Troubleshooting

| Symptom | Cause and fix |
|---|---|
| Provider shows "Not configured" | The key is empty or the backend was not restarted after editing `backend/.env` |
| "Claude rejected the API key" / "Authentication failed" | Wrong or revoked `ANTHROPIC_API_KEY` |
| "Claude model '...' was not found" | Typo in `ANTHROPIC_MODEL` |
| "Sarvam rejected the API key" | Wrong `SARVAM_API_KEY` (Sarvam returns 403 for a bad key) |
| "Paytm rejected the credentials" | Wrong or expired `PAYTM_CLIENT_ID` / `PAYTM_ACCESS_TOKEN` |
| AI text is marked "safe fallback used" | The live call failed or its output was rejected. See Logs and errors on `/demo-control` |
| Voice note returns a mock transcript | Live mode is off, or Sarvam rejected the audio (it accepts up to 30 seconds; WAV, MP3, AAC, FLAC or OGG) |

## Keeping keys safe

- Keys live only in `backend/.env` or the backend's environment. The browser never receives them; there are no
  `VITE_` key variables.
- `.env` is in `.gitignore`. Do not paste keys into `.env.example`, code, screenshots or chat.
- `GET /api/ai/status` reports only whether a key is present, never its value.
