# Demo guide

Everything below works in mock mode with no API keys and no internet.

## Start

```bash
cd backend && .venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000
cd frontend && npm run dev -- --host 127.0.0.1
```

Open http://127.0.0.1:5173. Before presenting, open http://127.0.0.1:5173/demo-control, sign in with the advisor passcode
(`LOANKART_ADVISOR_PASSWORD` in `backend/.env`, or the one printed in the backend terminal at start-up) and press
**Reset all demo data → Yes, reset everything**. The borrower journey itself needs no sign-in; the advisor workspace (step 19 onwards) asks for the passcode once.

## The primary borrower

Karthik Ramesh, KR Fabrics & Readymades, a fictional textile wholesaler in Tiruppur. He told us sales are ₹6.5 lakh a
month. His bank statements show ₹4.9 lakh of credits, of which ₹4.3 lakh are sales; GST returns show ₹4.1 lakh. He has
two running loans, one returned EMI, two late GST filings, and a ₹15 lakh working-capital loan was rejected.

Two ways to load him:
- From the landing page: **Open the demo case** (loads the case and its documents).
- Through onboarding: **My loan was rejected → Use the synthetic demo borrower → Save and continue**.

## The full journey (about six minutes)

| # | Where | Do | What to point out |
|---|---|---|---|
| 1 | Landing | **Start with my rejected loan** | Not a chatbot: documents → findings → options → next steps |
| 2 | Onboarding | **Use the synthetic demo borrower**, then **Save and continue** | One question at a time, "Why we ask", "I'm not sure" |
| 3 | Investigate | **Load the synthetic document pack**; open any PDF | 48 real PDF files generated from one dataset |
| 4 | Investigate | Tick the permission box, **Give permission**, **Run the investigation** | Task states are real and change live; each has a detail view |
| 5 | Investigate | Read the right-hand panel | Every figure carries a label: verified, extracted, told by you, calculated |
| 6 | Understand | **Explain the findings**; open "How we know" on the first finding | "Possible factor", never "the reason"; evidence links open the source PDF |
| 7 | Understand | Answer the three questions (choose "My own or family money" twice) | Unidentified credits were not counted as sales until confirmed |
| 8 | Improve | Set fresh funds to 8,00,000, tenure 60 months, Neithal loan → **Close it using the new loan** | Cover goes from 0.71x to 1.35x; total interest rises and is shown beside the lower EMI |
| 9 | Improve | Open two of the eight levers; **Compare financing options** | Each lever shows cost, risk and simulated lender fit |
| 10 | Compare | Read "How options are ranked"; change the priority to "Avoid offering security" and back | Disclosed weights; ranking changes with the priority |
| 11 | Compare | Tick **Compare** on three options | Table on desktop, stacked cards on a phone |
| 12 | Compare | Open "Why it ranks here" on the first card | Four separate sources: simulated criteria, expert note, synthetic history, AI commentary |
| 13 | Compare | **Review this option** on Gold-backed Business Overdraft | |
| 14 | Prepare | **Open the draft as a PDF**; tick the three checkpoints; **Submit the simulated application** | "DRAFT FOR REVIEW — NOT A SANCTION LETTER." |
| 15 | Track | **Check for a lender update (simulated)** | Two lender queries, each labelled simulated |
| 16 | Track | For each query: **Draft a reply from my documents**, then **Send reply** | AI drafts, the borrower approves |
| 17 | Track | **Check for a lender update (simulated)** again | Simulated offer of ₹8,00,000, marked "Not a real offer" |
| 18 | Track | **Ask an advisor to review**, type a reason, **Send to an advisor** | The whole case goes with the request |
| 19 | Advisor | Open the case; **Accept** a finding; under "EMI returns in 12 months" choose **Correct this value**, enter 0 and a source; add a note and **Mark case resolved** | Attributed, logged, original value kept |
| 20 | Advisor → Knowledge review | Type or record how the case was solved; **Structure as a candidate**; **Approve for reuse** | Inactive until approved; labelled practical experience, not lender policy |
| 21 | Demo control | **Compare with ground truth** | What was read from the PDFs matches the dataset on all eight figures; the advisor's correction is shown beside its row, not counted as a match |
| 22 | Demo control | **Reset all demo data** | Back to the start; the run repeats identically |

## Triggering lender events on demand

On `/demo-control`, under **Case tools**, pick the case (it needs a submitted application, step 14):

- **Trigger a lender query**: adds a non-routine query the documents cannot answer. Use it to motivate escalation.
- **Trigger a simulated rejection**: the tracking page then links back to the diagnosis and the other options.
- **Trigger an alternative offer**: an offer at 70% of the proposed amount.

Each appears on the borrower's Track page (refresh it) and in the timeline as "(simulated)".

## Showing human escalation

Step 18 above, or after a forced non-routine query. Then open **Advisor → Escalations**. The case shows the borrower's
reason, an AI-written handover summary, the findings, the options, the application history and the audit trail.

## Other borrowers

On `/demo-control`, under **Synthetic borrowers**, press **Load** then **Open case**:

| Borrower | Shows |
|---|---|
| Sri Lakshmi Engineering Works | Heavy EMIs: no lender fits as requested; a recovery plan appears; consolidating loans opens a route |
| Annam Provision Stores | Bank receipts far above GST turnover: flagged as "requires confirmation", not as wrongdoing |
| Thendral Cloud Kitchen | Ten-month-old business: most lenders reject on age; one early-stage product fits |
| Vetri Logistics | Strong cash flow, missing statements: "additional documentation required", then human review |
| Meenakshi Granites & Tiles | Large amount: unsecured products cap out; property-backed products fit |

## If the internet fails

Nothing changes: mock mode makes no external calls. If the page was in Live AI mode, press **Mock (no external calls)**
on `/demo-control`; even without doing so, a failed live call falls back to mock text and says so.

## If something looks wrong

1. `/demo-control` → **Logs and errors**.
2. **Reset all demo data**.
3. Restart the backend. A schema change rebuilds demo data automatically at start-up.
