// Frontend <-> backend integration check through the Vite dev proxy (the path the browser uses), in mock mode.
// Walks the whole borrower journey and checks the response fields the pages read.
// Usage: node scripts/check-journey.mjs [frontendUrl]   (default http://127.0.0.1:5173). Resets demo data first and last.
import assert from "node:assert/strict";

const base = process.argv[2] ?? "http://127.0.0.1:5173";
const CASE = "case-tiruppur-textile";
let step = 0;

async function call(method, path, body, headers = {}) {
  const res = await fetch(base + path, { method, headers: { ...(body ? { "Content-Type": "application/json" } : {}), ...headers }, body: body && JSON.stringify(body) });
  const type = res.headers.get("content-type") ?? "";
  return { status: res.status, body: type.includes("json") ? await res.json() : await res.arrayBuffer(), type };
}
async function ok(method, path, body, headers, status = 200) {
  const r = await call(method, path, body, headers);
  assert.equal(r.status, status, `${method} ${path} -> ${r.status} ${JSON.stringify(r.body).slice(0, 200)}`);
  console.log(`ok  ${String(++step).padStart(2)}  ${method.padEnd(4)} ${path}`);
  return r.body;
}
const has = (obj, keys) => keys.forEach((k) => assert.ok(k in obj, `missing field '${k}'`));

const page = await fetch(base + "/case/x/investigation");
assert.equal(page.status, 200); assert.match(await page.text(), /<div id="root">/);
await ok("GET", "/health");
await ok("POST", "/api/demo/reset");

const c = await ok("POST", "/api/demo/load", { scenario_id: "tiruppur_textile" });
has(c, ["id", "borrower", "stages", "consents", "escalation", "ai_mode", "is_synthetic"]);
assert.equal(c.ai_mode, "mock");

const docs = await ok("GET", `/api/cases/${CASE}/documents`);
assert.equal(docs.length, 48); has(docs[0], ["group", "title", "status", "url", "checks", "warnings"]);
const pdf = await call("GET", docs[0].url);
assert.equal(pdf.type, "application/pdf"); assert.equal(Buffer.from(pdf.body).subarray(0, 4).toString(), "%PDF");
console.log(`ok  ${String(++step).padStart(2)}  GET  ${docs[0].url} (real PDF through the proxy)`);

await ok("POST", `/api/cases/${CASE}/consents`, { key: "analyse_documents", granted: true });
let inv = await ok("POST", `/api/cases/${CASE}/investigation/run`, undefined, undefined, 202);
for (let i = 0; i < 100 && inv.status === "running"; i++) { await new Promise((r) => setTimeout(r, 300)); inv = (await call("GET", `/api/cases/${CASE}/investigation`)).body; }
assert.equal(inv.status, "complete");
has(inv, ["tasks", "headline", "metrics", "months", "reconciliation", "findings", "clarifications", "obligations", "lender_snapshot", "pacing_note"]);
has(inv.findings[0], ["severity", "verification_label", "explanation", "figures", "evidence", "next_action"]);
assert.equal(inv.metrics.avg_business_receipts, 430500);
console.log(`ok  ${String(++step).padStart(2)}  investigation complete: ${inv.findings.length} findings, ${inv.tasks.length} real task states`);

for (const q of inv.clarifications) inv = await ok("POST", `/api/cases/${CASE}/clarifications/${q.id}`, { answer: q.id.startsWith("credit-") ? "owner_contribution" : "estimate_high" });
const summary = (await ok("POST", `/api/cases/${CASE}/investigation/explain`)).summary;
assert.equal(summary.provider, "mock");

const base0 = await ok("GET", `/api/cases/${CASE}/restructure`);
has(base0, ["inputs", "current", "proposed", "dimensions", "assumptions", "saved", "paytm"]); assert.equal(base0.dimensions.length, 8);
const costly = inv.obligations.find((o) => o.rate === 21).account_no;
const saved = await ok("PUT", `/api/cases/${CASE}/restructure`, { ...base0.inputs, amount: 800000, tenure_months: 60, liability_actions: { [costly]: { action: "consolidate" } } });
assert.ok(saved.saved && saved.proposed.dscr > saved.current.dscr);

const recs = await ok("GET", `/api/cases/${CASE}/recommendations`);
assert.equal(recs.lenders_evaluated, 8); assert.equal(recs.products_evaluated, 16);
has(recs.options[0], ["rank", "score", "score_factors", "status_label", "fresh_funds", "monthly_payment", "apr_pct", "risks", "required_changes", "rules", "source", "expert_notes", "historical_outcomes"]);

const proposal = await ok("POST", `/api/cases/${CASE}/selection`, { product_id: recs.options[0].product_id });
assert.equal(proposal.disclaimer, "DRAFT FOR REVIEW — NOT A SANCTION LETTER.");
for (const cp of proposal.checkpoints) await ok("POST", `/api/cases/${CASE}/proposal/checkpoints`, { key: cp.key, done: true });
let app = await ok("POST", `/api/cases/${CASE}/application/submit`);
has(app, ["status_label", "banner", "reference", "queries", "offer", "events", "next_step", "failed_rules"]);
app = await ok("POST", `/api/cases/${CASE}/application/advance`);
for (const q of app.queries) {
  const drafted = await ok("POST", `/api/cases/${CASE}/application/queries/${q.id}/draft`);
  app = await ok("POST", `/api/cases/${CASE}/application/queries/${q.id}/respond`, { text: drafted.queries.find((x) => x.id === q.id).draft.body });
}
app = await ok("POST", `/api/cases/${CASE}/application/advance`);
assert.equal(app.status, "offer_generated"); assert.ok(app.events.every((e) => e.simulated));

await ok("POST", `/api/cases/${CASE}/escalate`, { reason: "Integration check" });
const advisor = { "X-LoanKart-Role": "advisor" };
assert.equal((await call("GET", "/api/advisor/cases")).status, 403);
const queue = await ok("GET", "/api/advisor/cases?status=escalated", undefined, advisor);
assert.equal(queue[0].case_id, CASE);
has(await ok("GET", `/api/advisor/cases/${CASE}`, undefined, advisor), ["case", "investigation", "restructure", "recommendations", "application", "comments", "audit", "correctable"]);
has(await ok("GET", "/api/demo/state"), ["ai_mode", "cases", "application_events", "lenders", "products"]);
has(await ok("GET", "/api/ai/status"), ["mode", "effective_mode", "providers", "note"]);
await ok("POST", "/api/demo/reset");

console.log("\nJourney check passed: frontend proxy and backend agree on every step, in mock mode, with no API keys.");
