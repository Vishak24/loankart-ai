"""Synthetic environment, document round trip, investigation, lender simulator, restructuring and ranking."""

import ast
import hashlib
from pathlib import Path

import pytest

from app import analysis, calculations as calc, recommendations, restructuring
from app.docgen import generate_pack
from app.extraction import extract_document
from app.lenders import DECISIONS, VIABLE, evaluate, load_catalogue
from app.synthetic import PRIMARY_SCENARIO, SCENARIOS, build_dataset, scenario_from_profile

APP = Path(__file__).parent.parent / "app"
PRODUCTS = load_catalogue()["products"]


@pytest.fixture(scope="module")
def packs(tmp_path_factory):
    """dataset, extracted docs, analysis result and lender facts for every scenario, built once."""
    root, out = tmp_path_factory.mktemp("packs"), {}
    for sid, scenario in SCENARIOS.items():
        dataset = build_dataset(scenario)
        manifest = generate_pack(dataset, root / sid)
        docs = [{"id": m["stem"], "title": m["title"], "extraction": extract_document(root / sid / m["filename"])}
                for m in manifest]
        result = analysis.analyse(docs, dataset["profile"])
        out[sid] = {"dataset": dataset, "dir": root / sid, "manifest": manifest, "docs": docs, "result": result,
                    "facts": analysis.build_facts(result, dataset["profile"])}
    return out


# ---------------------------------------------------------------------------------------------- layer separation

@pytest.mark.parametrize("module", ["extraction", "analysis", "investigation", "lenders", "restructuring",
                                    "recommendations", "calculations"])
def test_investigation_code_never_imports_the_ground_truth(module):
    tree = ast.parse((APP / f"{module}.py").read_text())
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            imported |= {node.module or ""} | {a.name for a in node.names}
        elif isinstance(node, ast.Import):
            imported |= {a.name for a in node.names}
    assert not imported & {"synthetic", "docgen", "environment", "demo_data"}, imported


# ---------------------------------------------------------------------------------------------- synthetic data

def test_primary_scenario_matches_the_brief(packs):
    truth = packs[PRIMARY_SCENARIO]["dataset"]["truth"]
    assert packs[PRIMARY_SCENARIO]["dataset"]["profile"]["monthly_revenue"] == 650_000     # declared
    assert truth["avg_total_credits"] == 490_000 and truth["avg_gst_turnover"] == 410_000
    assert truth["emi_returns"] == 1 and truth["late_gst_filings"] == 2
    assert truth["avg_business_receipts"] < truth["avg_total_credits"]        # not every credit is revenue


@pytest.mark.parametrize("sid", list(SCENARIOS))
def test_dataset_is_coherent(packs, sid):
    d = packs[sid]["dataset"]
    assert build_dataset(SCENARIOS[sid]) == d                                 # deterministic
    for st in d["bank"]["statements"]:
        balance = st["opening_balance"]
        for t in st["transactions"]:
            balance += t["credit"] - t["debit"]
            assert t["balance"] == balance >= 0                               # a current account never goes negative
        assert st["closing_balance"] == balance
    fin = d["financials"]
    if fin:
        bs, cf = fin["balance_sheet"], fin["cash_flow"]
        assert bs["total_assets"] == bs["capital"] + bs["secured_loans"] + bs["unsecured_loans"] + bs["creditors"]
        assert bs["capital"] > 0 and fin["pnl"]["cost_of_goods_sold"] > 0
        assert cf["closing_cash"] - cf["opening_cash"] == cf["net_change_in_cash"]
        assert fin["pnl"]["net_profit"] == d["itr"][-1]["net_income"]
    for loan in d["loans"]:
        assert loan["emi"] == calc.emi(loan["principal"], loan["rate"], loan["tenure"])


def test_documents_are_real_pdfs_and_regenerate_identically(packs, tmp_path):
    pack = packs[PRIMARY_SCENARIO]
    assert len(pack["manifest"]) == 48
    types = {m["doc_type"] for m in pack["manifest"]}
    assert types == {"bank_statement", "gstr3b", "gstr1", "itr", "loan_statement", "repayment_history", "pnl",
                     "balance_sheet", "cash_flow", "rejection_letter", "udyam_certificate", "gst_certificate",
                     "collateral_valuation"}
    generate_pack(pack["dataset"], tmp_path)
    for m in pack["manifest"]:
        a, b = (pack["dir"] / m["filename"]).read_bytes(), (tmp_path / m["filename"]).read_bytes()
        assert a.startswith(b"%PDF") and hashlib.sha256(a).digest() == hashlib.sha256(b).digest()


def test_changing_the_dataset_changes_the_documents(tmp_path):
    scenario = {**SCENARIOS[PRIMARY_SCENARIO], "receipts": [r + 10_000 for r in SCENARIOS[PRIMARY_SCENARIO]["receipts"]]}
    generate_pack(build_dataset(scenario), tmp_path)
    fields = extract_document(tmp_path / "bank_statement_2025-11.pdf")["fields"]
    original = build_dataset(SCENARIOS[PRIMARY_SCENARIO])["bank"]["statements"][0]
    assert fields["total_credits"] == sum(t["credit"] for t in original["transactions"]) + 10_000


# ---------------------------------------------------------------------------------------------- extraction and analysis

@pytest.mark.parametrize("sid", list(SCENARIOS))
def test_extraction_round_trips_every_transaction(packs, sid):
    by_id = {d["id"]: d["extraction"] for d in packs[sid]["docs"]}
    assert all(e["doc_type"] and not e["warnings"] for e in by_id.values())
    assert all(c["ok"] for e in by_id.values() for c in e["checks"])
    for st in packs[sid]["dataset"]["bank"]["statements"]:
        rows = by_id[f"bank_statement_{st['month']}"]["rows"]
        assert [(r["date"], r["narration"], r["debit"], r["credit"], r["balance"]) for r in rows] == \
               [(t["date"], t["narration"], t["debit"], t["credit"], t["balance"]) for t in st["transactions"]]


def test_unreadable_and_unknown_files_do_not_crash(tmp_path):
    (tmp_path / "junk.pdf").write_bytes(b"not a pdf")
    result = extract_document(tmp_path / "junk.pdf")
    assert result["doc_type"] is None and result["warnings"]


@pytest.mark.parametrize("sid", list(SCENARIOS))
def test_analysis_reproduces_ground_truth_from_documents_alone(packs, sid):
    truth, m = packs[sid]["dataset"]["truth"], packs[sid]["result"]["metrics"]
    months = packs[sid]["result"]["months"]
    for mine, theirs in zip(months, truth["monthly"]):
        assert mine["total_credits"] == theirs["total_credits"]
        assert mine["operating_expenses"] == theirs["operating_expenses"]
        assert mine["loan_repayments"] == theirs["loan_repayments"]
        assert mine["business_receipts"] == theirs["business_receipts"]       # ambiguous credits are never counted
    assert m["existing_emi"] == truth["active_emi_total"]
    assert m["outstanding_total"] == truth["active_outstanding_total"]
    assert m["emi_returns_12m"] == truth["emi_returns"] and m["late_gst_filings"] == truth["late_gst_filings"]
    assert m["avg_gst_turnover"] == truth["avg_gst_turnover"]


def test_classifier_matches_true_categories_except_deliberately_ambiguous_credits(packs):
    wrong = [(t["narration"], t["category"], analysis.classify(t)[0])
             for st in packs[PRIMARY_SCENARIO]["dataset"]["bank"]["statements"] for t in st["transactions"]
             if analysis.classify(t)[0] != t["category"]]
    assert sorted(w[0] for w in wrong) == ["IMPS CR-P SELVI", "NEFT CR-R KUMARESAN"]
    assert {w[2] for w in wrong} == {"unclassified_credit"}                   # asked about, not guessed


@pytest.mark.parametrize("sid, expected", [
    ("high_emi", {"existing_obligations", "repayment_capacity"}), ("gst_mismatch", {"gst_bank_mismatch"}),
    ("low_vintage", {"business_vintage", "documentation_gaps"}), ("incomplete_docs", {"documentation_gaps"}),
    ("collateral_backed", {"collateral_available"})])
def test_each_scenario_surfaces_the_problem_it_was_built_around(packs, sid, expected):
    assert expected <= {f["id"] for f in packs[sid]["result"]["findings"]}


def test_findings_are_structured_and_carefully_worded(packs):
    for sid in SCENARIOS:
        for f in packs[sid]["result"]["findings"]:
            assert {"id", "category", "title", "severity", "verification_state", "explanation", "figures", "evidence",
                    "source_documents", "unresolved_questions", "next_action", "dimension"} <= set(f)
            assert f["evidence"] or f["id"] == "documentation_gaps"
            text = (f["title"] + f["explanation"]).lower()
            assert "fraud" not in text and "rejected because" not in text and "misrepresent" not in text
    gst = next(f for f in packs["gst_mismatch"]["result"]["findings"] if f["id"] == "gst_bank_mismatch")
    assert gst["verification_state"] == "requires_confirmation" and "not evidence of wrongdoing" in gst["explanation"]


def test_borrower_answers_and_advisor_corrections_change_the_result_explicitly(packs):
    pack = packs[PRIMARY_SCENARIO]
    credit = next(c for c in pack["result"]["clarifications"] if c["id"].startswith("credit-"))
    answered = analysis.analyse(pack["docs"], pack["dataset"]["profile"], {credit["id"]: "business_receipt"})
    assert answered["metrics"]["avg_business_receipts"] > pack["result"]["metrics"]["avg_business_receipts"]
    corrected = analysis.analyse(pack["docs"], pack["dataset"]["profile"], None,
                                 {"existing_emi": {"value": 40_000, "by": "advisor"}})
    row = next(h for h in corrected["headline"] if h["key"] == "existing_emi")
    assert (row["value"], row["original"], row["state"]) == (40_000, 49_690, "corrected")   # original evidence kept


def test_custom_borrower_pack_follows_the_profile(tmp_path):
    profile = {**SCENARIOS["gst_mismatch"]["profile"], "monthly_revenue": 200_000, "monthly_expenses": 150_000,
               "existing_loan_count": 1, "outstanding_loan_amount": 150_000, "monthly_emi": 9_000,
               "business_vintage_years": 3.0}
    dataset = build_dataset(scenario_from_profile(profile, "abc"))
    manifest = generate_pack(dataset, tmp_path)
    docs = [{"id": m["stem"], "title": m["title"], "extraction": extract_document(tmp_path / m["filename"])} for m in manifest]
    m = analysis.analyse(docs, profile)["metrics"]
    assert m["existing_emi"] == 9_000 and m["vintage_years"] == 3.0
    assert 0.85 * 200_000 <= m["avg_business_receipts"] <= 200_000


# ---------------------------------------------------------------------------------------------- lender simulator

def test_catalogue_has_eight_fictional_lenders_with_versioned_policies():
    assert len({p["lender_id"] for p in PRODUCTS}) == 8 and len(PRODUCTS) == 16
    assert {p["lender_type"] for p in PRODUCTS} >= {"Bank", "NBFC"}
    assert len({p["category"] for p in PRODUCTS}) == 6
    for p in PRODUCTS:
        assert "(fictional)" in p["lender_name"] and p["verification_status"] == "simulated"
        assert p["version"] >= 1 and p["effective_date"] and p["source"] and p["min_amount"] < p["max_amount"]


def test_every_decision_is_reachable_and_deterministic(packs):
    seen = set()
    for sid in SCENARIOS:
        for p in PRODUCTS:
            first = evaluate(p, packs[sid]["facts"])
            assert first == evaluate(p, packs[sid]["facts"])
            assert first["simulated_status"].startswith("Simulated") and first["rules"]
            assert first["passed"] + first["failed"] + first["unresolved"] == len(first["rules"])
            seen.add(first["decision"])
    # with nothing else wrong, an unanswered question holds the application for clarification
    clean = {**packs["gst_mismatch"]["facts"], "open_clarifications": 1}
    seen.add(evaluate(next(p for p in PRODUCTS if p["id"] == "vcf-bl"), clean)["decision"])
    assert seen == set(DECISIONS)


def test_simulator_applies_each_lenders_own_rules(packs):
    facts = packs[PRIMARY_SCENARIO]["facts"]
    by_id = {p["id"]: evaluate(p, facts) for p in PRODUCTS}
    assert by_id["ktb-wctl"]["decision"] == "application_rejected"            # the lender in the rejection letter
    assert "EMI returns" in by_id["ktb-wctl"]["explanation"]
    assert by_id["ktb-lap"]["decision"] == "collateral_not_satisfied"         # gold is not property
    od = by_id["nvb-od"]
    assert od["decision"] == "alternative_amount_offered" and od["suggested_amount"] == 840_000    # 75% of 11,20,000
    assert od["monthly_payment"] == calc.interest_only_payment(840_000, 11.5) == 8_050
    assert od["dscr_after"] == calc.dscr(74_150, 49_690 + 8_050) and od["ltv_pct"] == 75.0
    # the same borrower fits or fails depending on the policy, never on a universal threshold
    assert len({r["decision"] for r in by_id.values()}) >= 4


def test_suggested_amount_always_satisfies_the_policy(packs):
    for sid in SCENARIOS:
        for p in PRODUCTS:
            r = evaluate(p, packs[sid]["facts"])
            if r["suggested_amount"]:
                assert p["min_amount"] <= r["suggested_amount"] <= p["max_amount"]
                assert r["dscr_after"] >= p["min_dscr"]
                if p["max_foir_pct"]:
                    assert r["foir_after_pct"] <= p["max_foir_pct"]
                if r["ltv_pct"] is not None:
                    assert r["ltv_pct"] <= p["max_ltv_pct"]


# ---------------------------------------------------------------------------------------------- restructuring, ranking

def test_restructuring_shows_before_and_after_with_costs(packs):
    pack = packs[PRIMARY_SCENARIO]
    profile, base, result = pack["dataset"]["profile"], pack["facts"], pack["result"]
    costly = next(o for o in result["obligations"] if o["rate"] == 21.0)
    inputs = {**restructuring.default_inputs(profile), "amount": 800_000, "tenure_months": 60,
              "liability_actions": {costly["account_no"]: {"action": "consolidate"}}}
    out = restructuring.compute(inputs, base, result, profile, PRODUCTS, None)
    cur, new = out["current"], out["proposed"]
    assert cur["new_emi"] == calc.emi(1_500_000, 18, 36) == 54_229 and cur["dscr"] == 0.71
    assert new["loan_amount"] == 800_000 + costly["outstanding"] and new["existing_emi"] == 49_690 - costly["emi"]
    assert new["new_emi"] == calc.emi(new["loan_amount"], 18, 60) and new["dscr"] > 1.2
    assert new["products_viable"] > cur["products_viable"] - 1 and new["products_fitting_in_full"] > cur["products_fitting_in_full"]
    assert [d["key"] for d in out["dimensions"]] == ["amount", "tenure", "liabilities", "collateral", "product",
                                                     "evidence", "structure", "documentation"]
    tenure = next(d for d in out["dimensions"] if d["key"] == "tenure")
    assert tenure["emi_impact"] < 0 < tenure["total_repayment_impact"]          # lower EMI never hides higher cost
    for d in out["dimensions"]:
        assert {"current", "proposed", "financial_impact", "risks", "required_evidence", "lender_fit_before",
                "lender_fit_after"} <= set(d)
    assert "alter" in " ".join(next(d for d in out["dimensions"] if d["key"] == "documentation")["risks"]).lower()


def test_refinancing_changes_emi_through_the_engine(packs):
    pack = packs[PRIMARY_SCENARIO]
    loan = next(o for o in pack["result"]["obligations"] if o["rate"] == 21.0)
    inputs = {**restructuring.default_inputs(pack["dataset"]["profile"]),
              "liability_actions": {loan["account_no"]: {"action": "refinance", "rate": 16, "tenure": 48}}}
    facts = restructuring.apply(inputs, pack["facts"], pack["result"]["obligations"])
    assert facts["existing_emi"] == 49_690 - loan["emi"] + calc.emi(loan["outstanding"], 16, 48)


def test_ranking_is_explicit_deterministic_and_responds_to_priority(packs):
    pack = packs[PRIMARY_SCENARIO]
    facts = {**pack["facts"], "open_clarifications": 0}
    for priority, weights in recommendations.WEIGHTS.items():
        assert sum(weights.values()) == 100
        out = recommendations.recommend(facts, PRODUCTS, priority)
        assert out == recommendations.recommend(facts, PRODUCTS, priority)
        assert [o["score"] for o in out["options"]] == sorted((o["score"] for o in out["options"]), reverse=True)
        for o in out["options"]:
            assert o["score"] == pytest.approx(sum(f["contribution"] for f in o["score_factors"]), abs=0.3)
            assert o["decision"] in VIABLE and o["status_label"] and o["source"]["policy_version"]
    balanced = recommendations.recommend(facts, PRODUCTS, "balanced")["options"][0]
    unsecured = recommendations.recommend(facts, PRODUCTS, "no_collateral")["options"][0]
    assert balanced["product_id"] == "nvb-od" and unsecured["product_id"] != "nvb-od"


def test_no_suitable_lender_gives_a_recovery_plan(packs):
    out = recommendations.recommend(packs["high_emi"]["facts"], PRODUCTS)
    assert out["options"] == [] and len(out["unsuitable"]) == 16
    plan = out["recovery_plan"]
    assert plan["blocking_reasons"] and any("advisor" in step for step in plan["steps"])
    assert any("Restructure" in step for step in plan["steps"])


def test_document_ai_output_is_flattened_to_what_the_parser_reads(tmp_path):
    """Sarvam Vision returns a ZIP of Markdown or HTML. Both must reach the same parser the PDFs go through."""
    import io
    import zipfile

    from app.extraction import parse_text
    from app.integrations.sarvam import lines_from_archive

    def archive(name: str, text: str) -> bytes:
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w") as z:
            z.writestr(name, text)
        return buffer.getvalue()

    markdown = ("# Ministry of MSME\n## UDYAM REGISTRATION CERTIFICATE\n\n| Field | Value |\n|---|---|\n"
                "| Udyam registration number | UDYAM-TN-00-0000451 |\n| Date of commencement of business | 10-05-2022 |\n"
                "| Major activity | Wholesale of textiles |\n")
    page = ("<h1>Ministry of MSME</h1><h2>UDYAM REGISTRATION CERTIFICATE</h2><table>"
            "<tr><td>Udyam registration number</td><td>UDYAM-TN-00-0000451</td></tr>"
            "<tr><td>Date of commencement of business</td><td>10-05-2022</td></tr>"
            "<tr><td>Major activity</td><td>Wholesale of textiles</td></tr></table>")
    for data in (archive("out.md", markdown), archive("out.html", page)):
        result = parse_text([ln.lstrip("# ") for ln in lines_from_archive(data)])
        assert result["doc_type"] == "udyam_certificate" and result["fields"]["commenced"] == "2022-05-10"
