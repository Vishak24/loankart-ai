"""API behaviour outside the happy path: validation, persistence, state rules, provider failures, permissions."""

import pytest
from fastapi.testclient import TestClient

from app import integrations
from app.integrations.base import NarrativeDraft, ProviderError
from app.main import create_app
from tests.test_api import VALID
from tests.test_journey import CASE, ok


def investigated(client, scenario="tiruppur_textile"):
    case_id = ok(client.post("/api/demo/load", json={"scenario_id": scenario}))["id"]
    ok(client.post(f"/api/cases/{case_id}/consents", json={"key": "analyse_documents", "granted": True}))
    ok(client.post(f"/api/cases/{case_id}/investigation/run"), 202)
    assert ok(client.get(f"/api/cases/{case_id}/investigation"))["status"] == "complete"
    return case_id


def submitted(client, product_id, case_id):
    proposal = ok(client.post(f"/api/cases/{case_id}/selection", json={"product_id": product_id}))
    for cp in proposal["checkpoints"]:
        ok(client.post(f"/api/cases/{case_id}/proposal/checkpoints", json={"key": cp["key"], "done": True}))
    return ok(client.post(f"/api/cases/{case_id}/application/submit"))


# ---------------------------------------------------------------------------------------------- validation and errors

def test_unknown_resources_return_404(client):
    for path in ("/api/cases/nope", "/api/cases/nope/investigation", "/api/documents/nope/file",
                 "/api/demo/ground-truth/nope"):
        r = client.get(path)
        assert r.status_code == 404 and "not found" in r.json()["detail"].lower()
    assert client.post("/api/demo/load", json={"scenario_id": "nope"}).status_code == 404
    assert client.post("/api/cases", json={"borrower_id": "nope"}).status_code == 404


def test_steps_are_refused_until_their_prerequisites_are_met(client):
    for path in ("restructure", "recommendations", "proposal"):
        r = client.get(f"/api/cases/{CASE}/{path}")
        assert r.status_code == 409 and r.json()["detail"]
    assert client.post(f"/api/cases/{CASE}/application/submit").status_code == 409
    assert client.post(f"/api/cases/{CASE}/application/advance").status_code == 409
    assert client.post("/api/demo/trigger", json={"case_id": CASE, "action": "query"}).status_code == 409
    ok(client.post(f"/api/cases/{CASE}/consents", json={"key": "analyse_documents", "granted": True}))
    r = client.post(f"/api/cases/{CASE}/investigation/run")       # consent given but no documents loaded yet
    assert r.status_code == 409 and "documents" in r.json()["detail"]


def test_request_validation(client):
    case_id = investigated(client)
    base = ok(client.get(f"/api/cases/{case_id}/restructure"))["inputs"]
    for patch in ({"amount": 0}, {"tenure_months": 2}, {"product_categories": ["casino"]}, {"unexpected": 1},
                  {"liability_actions": {"X": {"action": "erase"}}}):
        assert client.put(f"/api/cases/{case_id}/restructure", json={**base, **patch}).status_code == 422
    assert client.put(f"/api/cases/{case_id}/restructure",
                      json={**base, "liability_actions": {"NOPE1": {"action": "consolidate"}}}).status_code == 409
    assert client.get(f"/api/cases/{case_id}/recommendations", params={"priority": "bribes"}).status_code == 422
    assert client.post(f"/api/cases/{case_id}/selection", json={"product_id": "ktb-wctl"}).status_code == 409   # not viable
    assert client.post(f"/api/cases/{case_id}/clarifications/revenue-gap", json={"answer": "made up"}).status_code == 409
    assert client.post(f"/api/cases/{case_id}/clarifications/nope", json={"answer": "x"}).status_code == 404
    assert client.post(f"/api/cases/{case_id}/consents", json={"key": "contacts", "granted": True}).status_code == 422
    assert client.post("/api/calculations/emi", json={"principal": 0, "annual_rate_pct": 12, "months": 12}).status_code == 422
    emi = ok(client.post("/api/calculations/emi", json={"principal": 100_000, "annual_rate_pct": 12, "months": 3}))
    assert emi["emi"] == 34_002 and emi["total_interest"] == 2_007 and len(emi["schedule"]) == 3


def test_uploads_are_validated_and_stored_safely(client, db_path):
    assert client.post(f"/api/cases/{CASE}/documents", files={"file": ("x.exe", b"MZ", "application/pdf")}).status_code == 422
    assert client.post(f"/api/cases/{CASE}/documents", files={"file": ("x.pdf", b"hello", "application/pdf")}).status_code == 422
    big = b"%PDF" + b"0" * (10 * 1024 * 1024 + 1)
    assert client.post(f"/api/cases/{CASE}/documents", files={"file": ("big.pdf", big, "application/pdf")}).status_code == 422
    ok(client.post(f"/api/cases/{CASE}/documents/synthetic"))
    docs = ok(client.get(f"/api/cases/{CASE}/documents"))
    letter = next(d for d in docs if d["doc_type"] == "rejection_letter")
    content = client.get(letter["url"]).content
    up = ok(client.post(f"/api/cases/{CASE}/documents", files={"file": ("../../evil name.pdf", content, "application/pdf")}), 201)
    assert up["status"] == "extracted" and up["doc_type"] == "rejection_letter" and up["source"] == "upload"
    assert "/" not in up["filename"] and ".." not in up["filename"].replace("..pdf", "")
    stored = list((db_path.parent / "files" / "uploads" / CASE).iterdir())
    assert len(stored) == 1 and stored[0].parent.parent.parent == db_path.parent / "files"


def test_state_persists_across_restarts(db_path):
    with TestClient(create_app()) as c1:
        case_id = investigated(c1)
        base = ok(c1.get(f"/api/cases/{case_id}/restructure"))["inputs"]
        ok(c1.put(f"/api/cases/{case_id}/restructure", json={**base, "amount": 700_000}))
    with TestClient(create_app()) as c2:      # fresh app, same database and files: nothing is lost on refresh or restart
        c2.cookies.update(c1.cookies)         # the borrower's browser still holds its session
        assert ok(c2.get(f"/api/cases/{case_id}/investigation"))["metrics"]["avg_business_receipts"] == 430_500
        assert ok(c2.get(f"/api/cases/{case_id}/restructure"))["inputs"]["amount"] == 700_000
        assert len(ok(c2.get(f"/api/cases/{case_id}/documents"))) == 48


def test_stale_database_from_milestone_one_is_upgraded(db_path):
    import sqlite3
    conn = sqlite3.connect(db_path)
    conn.executescript("CREATE TABLE borrowers (id TEXT PRIMARY KEY, is_demo INTEGER NOT NULL DEFAULT 0, profile TEXT NOT NULL,"
                       " evidence TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL);")
    old = {k: v for k, v in VALID.items()}
    import json
    conn.execute("INSERT INTO borrowers VALUES ('old1', 0, ?, NULL, 'x', 'x')", (json.dumps(old),))
    conn.execute("INSERT INTO borrowers VALUES ('demo-synthetic-001', 1, ?, '{}', 'x', 'x')", (json.dumps({**old, "monthly_emi": 48_500}),))
    conn.commit()
    conn.close()
    from tests.conftest import PASSCODE
    with TestClient(create_app()) as c:
        assert c.post("/api/auth/advisor/login", json={"password": PASSCODE}).status_code == 200
        assert ok(c.get("/api/borrowers/old1"))["business_name"] == "Asha Tiffin Centre"   # onboarding data survives
        assert ok(c.get("/api/demo/borrower"))["monthly_emi"] == 49_690                     # demo row reseeded


# ---------------------------------------------------------------------------------------------- a borrower who onboarded

def test_custom_borrower_can_complete_the_journey(client):
    borrower = ok(client.post("/api/borrowers", json={**VALID, "previously_rejected": True, "rejection_reason": "unknown",
                                                      "personal_monthly_income": None, "collateral": "gold",
                                                      "collateral_value": 400_000}), 201)
    case = ok(client.post("/api/cases", json={"borrower_id": borrower["id"], "intent": "rejected"}))
    assert not case["is_synthetic"] and case["scenario_id"] is None
    assert ok(client.post("/api/cases", json={"borrower_id": borrower["id"]}))["id"] == case["id"]      # one case per borrower
    assert ok(client.get(f"/api/cases/{case['id']}/documents")) == []
    docs = ok(client.post(f"/api/cases/{case['id']}/documents/synthetic"))
    assert len(docs) > 15 and all(d["source"] == "synthetic" for d in docs)
    assert not any(d["doc_type"] == "gstr3b" for d in docs)        # this borrower said they are not GST registered
    ok(client.post(f"/api/cases/{case['id']}/consents", json={"key": "analyse_documents", "granted": True}))
    ok(client.post(f"/api/cases/{case['id']}/investigation/run"), 202)
    inv = ok(client.get(f"/api/cases/{case['id']}/investigation"))
    assert inv["status"] == "complete" and inv["metrics"]["existing_emi"] == VALID["monthly_emi"]
    recs = ok(client.get(f"/api/cases/{case['id']}/recommendations"))
    assert recs["products_evaluated"] == 16 and (recs["options"] or recs["recovery_plan"])


# ---------------------------------------------------------------------------------------------- application paths

def test_application_rejected_path_and_no_lender_recovery(client):
    case_id = investigated(client, "high_emi")
    recs = ok(client.get(f"/api/cases/{case_id}/recommendations"))
    assert recs["options"] == [] and recs["recovery_plan"]["steps"]
    inv = ok(client.get(f"/api/cases/{case_id}/investigation"))
    actions = {o["account_no"]: {"action": "consolidate"} for o in inv["obligations"] if not o["secured"]}
    base = ok(client.get(f"/api/cases/{case_id}/restructure"))["inputs"]
    ok(client.put(f"/api/cases/{case_id}/restructure", json={**base, "amount": 600_000, "tenure_months": 60,
                                                             "liability_actions": actions}))
    recs = ok(client.get(f"/api/cases/{case_id}/recommendations"))
    assert recs["options"], "restructuring should open at least one route"
    app = submitted(client, recs["options"][0]["product_id"], case_id)
    assert app["status"] == "under_review"
    # an edit to the simulated policy changes the simulated decision: the decision comes from the rules, not from text
    product = next(p for p in ok(client.get("/api/lenders")) if p["id"] == recs["options"][0]["product_id"])
    assert TestClient(client.app).put(f"/api/lenders/{product['id']}", json={**product, "min_vintage_years": 50}).status_code == 401
    edited = ok(client.put(f"/api/lenders/{product['id']}", json={**product, "min_vintage_years": 50}))
    assert edited["version"] == product["version"] + 1
    app = ok(client.post(f"/api/cases/{case_id}/application/advance"))
    assert app["status"] == "rejected" and app["decision_label"] == "Application rejected"
    assert any(r["rule"] == "vintage" for r in app["failed_rules"]) and app["offer"] is None
    assert "(simulated)" in app["events"][-1]["title"]
    assert client.post(f"/api/cases/{case_id}/application/advance").status_code == 409


def test_missing_documents_lead_to_a_query_then_human_review(client):
    case_id = investigated(client, "incomplete_docs")
    recs = ok(client.get(f"/api/cases/{case_id}/recommendations"))
    option = next(o for o in recs["options"] if o["decision"] == "additional_documents_required")
    assert option["unresolved_conditions"] and option["status_label"].startswith("Conditional")
    submitted(client, option["product_id"], case_id)
    app = ok(client.post(f"/api/cases/{case_id}/application/advance"))
    assert app["status"] == "query_raised" and not app["queries"][-1]["routine"] and "Please provide" in app["queries"][-1]["text"]
    ok(client.post(f"/api/cases/{case_id}/application/queries/{app['queries'][-1]['id']}/respond", json={"text": "My accountant is preparing it."}))
    app = ok(client.post(f"/api/cases/{case_id}/application/advance"))
    assert app["status"] == "query_raised"
    ok(client.post(f"/api/cases/{case_id}/application/queries/{app['queries'][-1]['id']}/respond", json={"text": "Still pending."}))
    assert ok(client.post(f"/api/cases/{case_id}/application/advance"))["status"] == "human_review"


def test_paytm_evidence_needs_consent_and_is_never_treated_as_revenue(client):
    case_id = investigated(client)
    view = ok(client.get(f"/api/cases/{case_id}/restructure"))
    assert view["paytm"] is None
    assert client.put(f"/api/cases/{case_id}/restructure", json={**view["inputs"], "include_paytm_evidence": True}).status_code == 409
    ok(client.post(f"/api/cases/{case_id}/consents", json={"key": "paytm_evidence", "granted": True}))
    view = ok(client.put(f"/api/cases/{case_id}/restructure", json={**view["inputs"], "include_paytm_evidence": True}))
    p = view["paytm"]
    assert p["simulated"] and "Synthetic" in p["source"] and p["reconciles_with_bank"] and len(p["months"]) == 12
    assert p["total_gross"] > p["total_net"] and 10 < p["share_of_bank_receipts_pct"] < 14
    assert view["proposed"]["operating_surplus"] == view["current"]["operating_surplus"]       # figures unchanged
    ok(client.post(f"/api/cases/{case_id}/consents", json={"key": "paytm_evidence", "granted": False}))
    assert ok(client.get(f"/api/cases/{case_id}/restructure"))["inputs"]["include_paytm_evidence"] is False


# ---------------------------------------------------------------------------------------------- AI providers

class _Flaky:
    name = "flaky"
    calls = 0

    def generate(self, task, context):
        _Flaky.calls += 1
        raise ProviderError("simulated outage")


class _Hallucinating:
    name = "hallucinating"

    def generate(self, task, context):
        return NarrativeDraft(headline="Good news", body="Your surplus is 9,99,999 and the loan is pre-approved.")


class _Crashing:
    name = "crashing"

    def generate(self, task, context):
        raise RuntimeError("socket closed")


def test_mock_mode_makes_no_provider_calls_and_reports_status_honestly(client):
    status = ok(client.get("/api/ai/status"))
    assert status["mode"] == status["effective_mode"] == "mock"
    states = {p["name"]: p["state"] for p in status["providers"]}
    assert states["Claude (Anthropic)"] == "not_configured" and states["Mock AI provider"] == "mock"
    assert states["Paytm merchant evidence"] == "not_available"
    checked = ok(client.post("/api/ai/check"))
    assert all(p["state"] != "ok" for p in checked["providers"])          # nothing claims a live connection


def test_live_mode_without_credentials_falls_back_and_says_so(client):
    case_id = investigated(client)
    status = ok(client.put("/api/ai/mode", json={"mode": "live"}))
    assert status["mode"] == "live" and status["effective_mode"] == "mock" and "no API key" in status["note"]
    summary = ok(client.post(f"/api/cases/{case_id}/investigation/explain"))["summary"]
    assert summary["provider"] == "mock" and summary["fallback"] is True and summary["mode"] == "live"
    assert any("without credentials" in e["title"] for e in ok(client.get("/api/demo/logs")))
    ok(client.put("/api/ai/mode", json={"mode": "mock"}))


@pytest.mark.parametrize("provider, expected_log", [(_Flaky, "AI output rejected"), (_Hallucinating, "AI output rejected"),
                                                    (_Crashing, "AI provider failure")])
def test_provider_failures_never_break_the_case(client, monkeypatch, provider, expected_log):
    case_id = investigated(client)
    before = ok(client.get(f"/api/cases/{case_id}/investigation"))
    ok(client.put("/api/ai/mode", json={"mode": "live"}))
    monkeypatch.setattr(integrations.AIService, "_reasoners", lambda self: [provider])
    _Flaky.calls = 0
    after = ok(client.post(f"/api/cases/{case_id}/investigation/explain"))
    assert after["summary"]["fallback"] is True and after["summary"]["provider"] == "mock"
    assert "pre-approved" not in after["summary"]["body"] and "9,99,999" not in after["summary"]["body"]
    assert after["metrics"] == before["metrics"] and after["findings"] == before["findings"]     # state untouched
    assert any(expected_log in e["title"] for e in ok(client.get("/api/demo/logs")))
    if provider is _Flaky:
        assert _Flaky.calls == 2                                           # one retry, then the safe fallback


def test_grounding_check_catches_invented_figures():
    context = {"surplus": "₹74,150", "emi": 49690}
    assert integrations.ungrounded({"body": "Surplus is ₹74,150 against EMIs of 49,690."}, context) == []
    assert integrations.ungrounded({"body": "Surplus is ₹84,150."}, context) == ["84150"]


def test_speech_and_translation_degrade_honestly_in_mock_mode(client):
    assert TestClient(client.app).post("/api/ai/transcribe", files={"file": ("n.wav", b"RIFF", "audio/wav")}).status_code == 401
    t = ok(client.post("/api/ai/transcribe", files={"file": ("n.wav", b"RIFF", "audio/wav")}))
    assert t["provider"] == "mock" and t["text"].startswith("[Mock transcript")
    tr = ok(client.post("/api/ai/translate", json={"text": "Hello", "target_language": "ta-IN"}))
    assert tr["text"] == "Hello" and tr["fallback"] is True
    assert client.post("/api/ai/speak", json={"text": "Hello"}).status_code == 409


def test_knowledge_stays_separate_from_lender_policy(client):
    case_id = investigated(client)
    before = ok(client.get("/api/lenders"))
    entry = ok(client.post("/api/knowledge", json={
        "text": "Borrower had one returned EMI. A written explanation with the bank's confirmation was accepted. "
                "The lender then offered the overdraft.", "case_id": case_id, "source": "voice"}), 201)
    assert entry["status"] == "candidate" and entry["source"] == "Advisor voice note" and entry["version"] == 1
    recs = ok(client.get(f"/api/cases/{case_id}/recommendations"))
    assert all(entry["id"] not in [n["id"] for n in o["expert_notes"]] for o in recs["options"])      # inactive until approved
    assert ok(client.post(f"/api/knowledge/{entry['id']}/review", json={"decision": "reject"}))["status"] == "rejected"
    assert ok(client.get("/api/lenders")) == before                         # official criteria untouched
    assert client.post("/api/knowledge/nope/review", json={"decision": "approve"}).status_code == 404


def test_concurrent_requests_do_not_share_or_break_connections(client):
    """The browser loads several resources at once. Found in browser testing: sequential tests did not catch it."""
    from concurrent.futures import ThreadPoolExecutor
    case_id = investigated(client)
    paths = [f"/api/cases/{case_id}", f"/api/cases/{case_id}/documents", f"/api/cases/{case_id}/investigation",
             f"/api/cases/{case_id}/restructure", f"/api/cases/{case_id}/recommendations", "/api/demo/state"] * 6
    with ThreadPoolExecutor(max_workers=12) as pool:
        codes = list(pool.map(lambda path: client.get(path).status_code, paths))
    assert codes == [200] * len(paths)


def test_ground_truth_comparison_is_exact_and_not_fooled_by_corrections(client):
    case_id = investigated(client)
    ok(client.post(f"/api/advisor/cases/{case_id}/actions",
                   json={"type": "correct_value", "target": "emi_returns_12m", "value": 0, "note": "Bank letter"}))
    line = next(l for l in ok(client.get(f"/api/demo/ground-truth/{case_id}"))["comparison"] if l["metric"] == "EMI returns in 12 months")
    assert (line["ground_truth"], line["investigated"], line["match"]) == (1, 1, True)     # what the PDFs said
    assert "corrected this to 0" in line["note"]
    import json
    import sqlite3
    # a count that is off by one must never read as a match
    conn = sqlite3.connect(client.app.state.settings.db_path)
    data = json.loads(conn.execute("SELECT data FROM cases WHERE id = ?", (case_id,)).fetchone()[0])
    data["investigation"]["result"]["metrics"]["late_gst_filings"] = 3
    conn.execute("UPDATE cases SET data = ? WHERE id = ?", (json.dumps(data), case_id))
    conn.commit()
    conn.close()
    line = next(l for l in ok(client.get(f"/api/demo/ground-truth/{case_id}"))["comparison"] if l["metric"] == "Late GST filings")
    assert (line["ground_truth"], line["investigated"], line["match"]) == (2, 3, False)


def test_editing_answers_refreshes_everything_derived_from_them(client):
    case_id = investigated(client)
    borrower = ok(client.get("/api/demo/borrower"))
    profile = {k: v for k, v in borrower.items() if k not in ("id", "is_synthetic", "created_at", "updated_at")}
    ok(client.post(f"/api/cases/{case_id}/selection", json={"product_id": "nvb-od"}))
    ok(client.put(f"/api/borrowers/{borrower['id']}", json={**profile, "monthly_revenue": 440_000, "requested_amount": 500_000}))
    inv = ok(client.get(f"/api/cases/{case_id}/investigation"))
    assert inv["status"] == "complete" and inv["metrics"]["declared_monthly_revenue"] == 440_000
    assert "revenue_evidence_gap" not in {f["id"] for f in inv["findings"]}              # the gap is now 2%
    assert ok(client.get(f"/api/cases/{case_id}"))["stages"]["proposal"] == "locked"     # the old choice was cleared
    assert ok(client.get(f"/api/cases/{case_id}/restructure"))["inputs"]["amount"] == 500_000
    # a borrower who onboarded: their pack is rebuilt from the new answers and the investigation starts again
    mine = ok(client.post("/api/borrowers", json=VALID), 201)
    case = ok(client.post("/api/cases", json={"borrower_id": mine["id"]}))
    ok(client.post(f"/api/cases/{case['id']}/documents/synthetic"))
    ok(client.post(f"/api/cases/{case['id']}/consents", json={"key": "analyse_documents", "granted": True}))
    ok(client.post(f"/api/cases/{case['id']}/investigation/run"), 202)
    ok(client.put(f"/api/borrowers/{mine['id']}", json={**VALID, "monthly_emi": 15_000}))
    assert ok(client.get(f"/api/cases/{case['id']}/investigation"))["status"] == "not_started"
    ok(client.post(f"/api/cases/{case['id']}/investigation/run"), 202)
    assert ok(client.get(f"/api/cases/{case['id']}/investigation"))["metrics"]["existing_emi"] == 15_000


def test_approval_language_filter_allows_denials_but_not_claims():
    from app.integrations import claims_approval
    assert claims_approval("Your loan is pre-approved.") and claims_approval("This is a sanctioned amount.")
    assert claims_approval("Nothing to worry about. Approval is guaranteed.")
    assert not claims_approval("This is not a sanction and nothing here is guaranteed.")
    assert not claims_approval("An indicative match is never a sanctioned loan.")
    assert not claims_approval("Cover of 1.29x leaves a thin cushion.")
