"""End-to-end acceptance test: the complete borrower journey through the API in mock mode, from a clean reset,
run twice to prove the demo is repeatable. Mirrors the 17 acceptance steps in the project brief."""

import re

ADVISOR = {"X-LoanKart-Role": "advisor"}
CASE = "case-tiruppur-textile"
VOLATILE = re.compile(r'"(created_at|updated_at|started_at|finished_at|generated_at|raised_at|at)": ?"[^"]*"')


def ok(response, status=200):
    assert response.status_code == status, response.text
    return response.json()


def stable(response) -> str:
    """Response text with timestamps removed, for comparing two runs."""
    return VOLATILE.sub("", response.text)


def journey(client) -> dict[str, str]:
    snap: dict[str, str] = {}

    # 1-3: open LoanKart, choose rejected-loan recovery, load the borrower profile
    assert ok(client.post("/api/demo/reset"))["business_name"] == "KR Fabrics & Readymades"
    case = ok(client.post("/api/demo/load", json={"scenario_id": "tiruppur_textile"}))
    assert case["id"] == CASE and case["is_synthetic"] and case["stages"]["diagnosis"] == "locked"
    assert ok(client.post("/api/cases", json={"borrower_id": "demo-synthetic-001", "intent": "rejected"}))["id"] == CASE

    # 4: inspect synthetic documents (real PDF files)
    docs = ok(client.get(f"/api/cases/{CASE}/documents"))
    assert len(docs) == 48 and {d["group"] for d in docs} >= {"Banking", "GST", "Income tax", "Existing loans", "Rejection"}
    pdf = client.get(docs[0]["url"])
    assert pdf.status_code == 200 and pdf.content.startswith(b"%PDF") and pdf.headers["content-type"] == "application/pdf"

    # 5: run the investigation (consent first)
    assert client.post(f"/api/cases/{CASE}/investigation/run").status_code == 409
    ok(client.post(f"/api/cases/{CASE}/consents", json={"key": "analyse_documents", "granted": True}))
    ok(client.post(f"/api/cases/{CASE}/investigation/run"), 202)
    r = client.get(f"/api/cases/{CASE}/investigation")
    inv = ok(r)
    assert inv["status"] == "complete", inv
    assert [t["status"] for t in inv["tasks"]] == ["complete"] * 7 + ["needs_input", "complete"]
    snap["investigation"] = stable(r)

    # 6-7: extracted findings and potential rejection factors, each with evidence
    m = inv["metrics"]
    assert (m["avg_total_credits"], m["avg_business_receipts"], m["avg_gst_turnover"]) == (490_000, 430_500, 410_000)
    assert m["emi_returns_12m"] == 1 and m["late_gst_filings"] == 2 and m["existing_emi"] == 49_690
    ids = {f["id"] for f in inv["findings"]}
    assert {"repayment_capacity", "revenue_evidence_gap", "emi_return", "late_gst_filings", "stated_rejection_reason",
            "unidentified_credits"} <= ids
    for f in inv["findings"]:
        assert f["evidence"] and f["verification_label"] and f["next_action"], f["id"]
        assert "rejected because" not in f["explanation"].lower()
    truth = ok(client.get(f"/api/demo/ground-truth/{CASE}"))
    assert all(line["match"] for line in truth["comparison"]), truth["comparison"]

    # the borrower confirms uncertain information; the analysis is recomputed
    for c in inv["clarifications"]:
        answer = "owner_contribution" if c["id"].startswith("credit-") else "undeposited_cash"
        inv = ok(client.post(f"/api/cases/{CASE}/clarifications/{c['id']}", json={"answer": answer}))
    assert "unidentified_credits" not in {f["id"] for f in inv["findings"]}
    assert inv["tasks"][7]["status"] == "complete"
    inv = ok(client.post(f"/api/cases/{CASE}/findings/emi_return/feedback", json={"action": "confirm", "note": "One-off"}))
    assert next(f for f in inv["findings"] if f["id"] == "emi_return")["feedback"]["action"] == "confirm"
    summary = ok(client.post(f"/api/cases/{CASE}/investigation/explain"))["summary"]
    assert summary["provider"] == "mock" and summary["mode"] == "mock" and not summary["fallback"]

    # 8-9: test restructuring options and see the financial consequences
    base = ok(client.get(f"/api/cases/{CASE}/restructure"))
    assert len(base["dimensions"]) == 8 and base["current"]["dscr"] == 0.71 and not base["saved"]
    costly = next(o for o in inv["obligations"] if o["rate"] == 21.0)["account_no"]
    scenario = {**base["inputs"], "amount": 800_000, "tenure_months": 60,
                "liability_actions": {costly: {"action": "consolidate"}}}
    preview = ok(client.post(f"/api/cases/{CASE}/restructure/preview", json=scenario))
    assert not preview["saved"] and preview["proposed"]["dscr"] > 1.2 > preview["current"]["dscr"]
    r = client.put(f"/api/cases/{CASE}/restructure", json=scenario)
    assert ok(r)["saved"] and ok(r)["proposed"]["total_interest"] > 0
    snap["restructure"] = stable(r)

    # 10-11: eight fictional lenders evaluated, ranked alternatives compared
    r = client.get(f"/api/cases/{CASE}/recommendations")
    recs = ok(r)
    assert recs["lenders_evaluated"] == 8 and recs["products_evaluated"] == 16
    assert len(recs["options"]) >= 3 and len(recs["options"]) + len(recs["unsuitable"]) == 16
    assert [o["rank"] for o in recs["options"]] == list(range(1, len(recs["options"]) + 1))
    assert sum(f["weight"] for f in recs["ranking"]["factors"]) == 100
    top = recs["options"][0]
    assert top["product_id"] == "nvb-od" and top["decision"] == "eligible" and "fictional" in top["lender_name"]
    assert top["expert_notes"] and top["historical_outcomes"] and top["source"]["verification_status"] == "simulated"
    snap["recommendations"] = stable(r)
    other = ok(client.get(f"/api/cases/{CASE}/recommendations", params={"priority": "no_collateral"}))
    assert other["options"][0]["product_id"] != "nvb-od"
    assert ok(client.post(f"/api/cases/{CASE}/recommendations/explain"))["options"][0]["ai_commentary"]["provider"] == "mock"

    # 12-13: select an option, generate the proposal
    proposal = ok(client.post(f"/api/cases/{CASE}/selection", json={"product_id": "nvb-od"}))
    assert proposal["disclaimer"] == "DRAFT FOR REVIEW — NOT A SANCTION LETTER." and proposal["status"] == "draft"
    assert client.get(proposal["pdf_url"]).content.startswith(b"%PDF")
    assert client.post(f"/api/cases/{CASE}/application/submit").status_code == 409      # checkpoints not confirmed
    for cp in proposal["checkpoints"]:
        proposal = ok(client.post(f"/api/cases/{CASE}/proposal/checkpoints", json={"key": cp["key"], "done": True}))
    assert proposal["status"] == "ready"

    # 14-15: simulate submission and track lender responses
    app = ok(client.post(f"/api/cases/{CASE}/application/submit"))
    assert app["status"] == "under_review" and app["reference"].startswith("SIM-NVB-") and app["simulated"]
    app = ok(client.post(f"/api/cases/{CASE}/application/advance"))
    assert app["status"] == "query_raised" and len(app["queries"]) == 2
    assert client.post(f"/api/cases/{CASE}/application/advance").status_code == 409      # query still open
    for q in app["queries"]:
        drafted = ok(client.post(f"/api/cases/{CASE}/application/queries/{q['id']}/draft"))
        text = next(x for x in drafted["queries"] if x["id"] == q["id"])["draft"]["body"]
        app = ok(client.post(f"/api/cases/{CASE}/application/queries/{q['id']}/respond", json={"text": text}))
    assert app["status"] == "info_supplied"
    r = client.post(f"/api/cases/{CASE}/application/advance")
    app = ok(r)
    assert app["status"] == "offer_generated" and app["offer"]["amount"] == 800_000
    assert app["offer"]["label"] == "Simulated lender offer" and "sanction" not in r.text.lower()
    assert all(e["simulated"] and e["title"].endswith("(simulated)") for e in app["events"])
    snap["application"] = stable(r)

    # 16: escalate to an advisor; the advisor reviews, corrects and resolves
    assert client.get("/api/advisor/cases").status_code == 403
    escalated = ok(client.post(f"/api/cases/{CASE}/escalate", json={"reason": "I want a person to check the offer."}))
    assert escalated["escalation"]["status"] == "open" and escalated["escalation"]["summary"]["body"]
    queue = ok(client.get("/api/advisor/cases", headers=ADVISOR))
    assert queue[0]["case_id"] == CASE and queue[0]["status"] == "escalated"
    for action in ({"type": "review_finding", "target": "emi_return", "decision": "accept", "note": "Seen in statement"},
                   {"type": "correct_value", "target": "emi_returns_12m", "value": 0, "note": "Bank confirmed a technical return"},
                   {"type": "comment", "note": "Gold OD is the right route."},
                   {"type": "review_solution", "decision": "accept", "note": "Agreed"},
                   {"type": "resolve", "note": "Explained the offer to the borrower."}):
        detail = ok(client.post(f"/api/advisor/cases/{CASE}/actions", json=action, headers=ADVISOR))
    assert detail["case"]["escalation"]["status"] == "resolved" and len(detail["comments"]) == 5
    corrected = next(h for h in detail["investigation"]["headline"] if h["key"] == "emi_returns_12m")
    assert (corrected["value"], corrected["original"], corrected["state"]) == (0, 1, "corrected")
    assert any(e["title"].startswith("Advisor action") for e in detail["audit"])
    entry = ok(client.post("/api/knowledge", headers=ADVISOR, json={
        "text": "The term loan EMI was above the monthly surplus. We moved the borrower to a gold-backed overdraft. "
                "The lender simulator made an offer after the EMI return was explained.", "case_id": CASE}), 201)
    assert entry["status"] == "candidate" and entry["approver"] is None
    approved = ok(client.post(f"/api/knowledge/{entry['id']}/review", json={"decision": "approve"}, headers=ADVISOR))
    assert approved["status"] == "approved" and "not lender policy" in approved["verification_status"]

    # demo control: forced lender events and state inspection
    assert ok(client.post("/api/demo/trigger", json={"case_id": CASE, "action": "rejection"}))["status"] == "rejected"
    assert ok(client.post("/api/demo/trigger", json={"case_id": CASE, "action": "alternative_offer"}))["offer"]["amount"] == 560_000
    assert ok(client.post("/api/demo/trigger", json={"case_id": CASE, "action": "query"}))["queries"][-1]["routine"] is False
    state = ok(client.get("/api/demo/state"))
    assert (state["lenders"], state["products"], state["ai_mode"]) == (8, 16, "mock")
    return snap


def test_complete_journey_is_repeatable_from_reset(client):
    first = journey(client)
    second = journey(client)      # 17: reset and repeat
    for key in first:
        assert first[key] == second[key], f"{key} differs between runs"


def test_reset_returns_to_the_initial_state(client):
    journey(client)
    client.post("/api/demo/reset")
    case = ok(client.get(f"/api/cases/{CASE}"))
    assert case["stages"] == {"investigation": "available", "diagnosis": "locked", "restructure": "locked",
                              "options": "locked", "proposal": "locked", "tracking": "locked"}
    assert case["consents"] == {"analyse_documents": False, "paytm_evidence": False, "share_with_lender": False}
    assert ok(client.get(f"/api/cases/{CASE}/documents")) == []          # packs are regenerated on demand
    assert [k["id"] for k in ok(client.get("/api/knowledge", headers=ADVISOR))] == ["kn-seed-gold-od"]
    assert ok(client.get("/api/demo/state"))["application_events"] == []
