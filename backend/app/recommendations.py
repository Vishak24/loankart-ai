"""Recommendation engine: evaluate every product, rank the viable ones with a disclosed scoring rubric.

The rubric is explicit and deterministic. An LLM never ranks lenders. Four kinds of information are returned
separately and never merged: official (simulated) lender criteria, expert-approved practical notes, synthetic
historical outcomes, and AI-generated commentary (added by the caller, labelled as such).
"""

from typing import Any

from .analysis import rs
from .lenders import VIABLE, evaluate

MIN_COVERAGE_PCT = 30   # an option covering less of the need than this is listed as unsuitable, not recommended

FACTORS = {
    "coverage": "How much of the amount you need it covers",
    "affordability": "Cash-flow cover after the new repayment (1.0x scores 0, 1.5x or more scores 100)",
    "cost": "Annual cost including fees (APR of 10% or less scores 100; each point above loses 5)",
    "evidence": "Share of this lender's rules already met with documents on file",
    "collateral": "Exposure of your assets (unsecured 100, movable security 40, property 20)",
    "speed": "Typical turnaround (2 days scores 100; each extra day loses 5)",
}
WEIGHTS = {
    "balanced": {"coverage": 25, "affordability": 25, "cost": 20, "evidence": 15, "collateral": 10, "speed": 5},
    "lowest_emi": {"coverage": 20, "affordability": 40, "cost": 15, "evidence": 10, "collateral": 10, "speed": 5},
    "lowest_cost": {"coverage": 20, "affordability": 20, "cost": 40, "evidence": 10, "collateral": 5, "speed": 5},
    "no_collateral": {"coverage": 20, "affordability": 20, "cost": 10, "evidence": 10, "collateral": 35, "speed": 5},
    "fastest": {"coverage": 25, "affordability": 20, "cost": 10, "evidence": 10, "collateral": 5, "speed": 30},
}
PRIORITY_LABELS = {"balanced": "Balanced", "lowest_emi": "Lowest monthly repayment", "lowest_cost": "Lowest total cost",
                   "no_collateral": "Avoid offering security", "fastest": "Fastest decision"}
STATUS = {"eligible": "Indicative match", "alternative_amount_offered": "Indicative match at a lower amount",
          "additional_documents_required": "Conditional match: documents needed",
          "clarification_required": "Conditional match: questions open"}


def _clamp(x: float) -> float:
    return round(max(0.0, min(100.0, x)), 1)


def score(product: dict[str, Any], result: dict[str, Any], facts: dict[str, Any]) -> dict[str, float]:
    total_rules = len(result["rules"]) or 1
    secured = product["collateral_required"]
    movable = secured and facts["collateral"] and facts["collateral"]["type"] in ("gold", "fixed_deposit", "machinery")
    return {
        "coverage": _clamp((result["fresh_funds"] or 0) / max(facts["requested_amount"], 1) * 100),
        "affordability": _clamp(((result["dscr_after"] or 0) - 1.0) / 0.5 * 100),
        "cost": _clamp(100 - ((result["apr_pct"] or 30) - 10) * 5),
        "evidence": _clamp(result["passed"] / total_rules * 100 + (5 if facts["supplementary_evidence"] else 0)),
        "collateral": 100.0 if not secured else (40.0 if movable else 20.0),
        "speed": _clamp(100 - (product["turnaround_days"] - 2) * 5),
    }


def _changes(product: dict[str, Any], result: dict[str, Any], facts: dict[str, Any]) -> list[str]:
    out = []
    if result["suggested_amount"] and result["suggested_amount"] < result["requested_amount"]:
        out.append(f"Accept {rs(result['fresh_funds'])} of fresh funds instead of {rs(facts['requested_amount'])}.")
    if product["collateral_required"] and facts["collateral"]:
        out.append(f"Offer your {facts['collateral']['type'].replace('_', ' ')} as security.")
    if result["takeover_amount"]:
        out.append(f"Close {facts['takeover']['count']} existing loan(s) with {rs(result['takeover_amount'])} of this loan.")
    if result["tenure_months"] != facts["tenure_months"]:
        out.append(f"Take a {result['tenure_months']}-month tenure.")
    if result["missing_documents"]:
        out.append("Provide: " + ", ".join(result["missing_documents"]) + ".")
    if facts["co_applicant_income"] and product["allows_co_applicant"] and product["income_method"] == "itr":
        out.append("Add the co-applicant with proof of income.")
    return out


def _risks(product: dict[str, Any], result: dict[str, Any]) -> list[str]:
    out = []
    if product["repayment_type"] == "interest_only":
        out.append("Interest-only: the full amount stays owed and falls due if the limit is not renewed.")
    if product["collateral_required"]:
        out.append("Secured: the asset can be sold by the lender if repayments are missed.")
    if (result["apr_pct"] or 0) >= 20:
        out.append(f"High cost: APR of {result['apr_pct']}% including fees.")
    if result["tenure_months"] >= 60:
        out.append("Long tenure: more interest is paid overall.")
    if result["takeover_amount"]:
        out.append("Consolidation can raise the total cost of the debt being moved.")
    if result["dscr_after"] is not None and result["dscr_after"] < 1.25:
        out.append(f"Thin cushion: cash-flow cover after this loan is {result['dscr_after']}x.")
    return out


def recommend(facts: dict[str, Any], products: list[dict[str, Any]], priority: str = "balanced",
              categories: list[str] | None = None, expert_notes: list[dict[str, Any]] | None = None,
              history: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    weights = WEIGHTS[priority]
    history_by_product = {h["product_id"]: h for h in history or []}
    options, unsuitable = [], []
    for p in products:
        r = evaluate(p, facts)
        source = {"policy_version": p["version"], "effective_date": p["effective_date"],
                  "verification_status": p["verification_status"], "description": p["source"]}
        base = {"product_id": p["id"], "lender_name": p["lender_name"], "lender_type": p["lender_type"],
                "product_name": p["product_name"], "category": p["category"], "decision": r["decision"],
                "decision_label": r["decision_label"], "explanation": r["explanation"], "rules": r["rules"],
                "source": source}
        coverage = (r["fresh_funds"] or 0) / max(facts["requested_amount"], 1) * 100
        excluded_by_choice = bool(categories) and p["category"] not in categories
        if r["decision"] not in VIABLE or coverage < MIN_COVERAGE_PCT or excluded_by_choice:
            reason = r["explanation"]
            if r["decision"] in VIABLE and excluded_by_choice:
                reason = "Left out because you filtered by type of loan."
            elif r["decision"] in VIABLE:
                reason = (f"Would cover only {rs(r['fresh_funds'] or 0)} ({round(coverage)}% of the need), below the "
                          f"{MIN_COVERAGE_PCT}% used as the cut-off for a recommendation.")
            unsuitable.append({**base, "reason": reason, "max_supported_amount": r["max_supported_amount"]})
            continue
        factors = score(p, r, facts)
        total = round(sum(factors[k] * weights[k] for k in weights) / 100, 1)
        hist = history_by_product.get(p["id"])
        options.append({
            **base, "rank": 0, "score": total,
            "score_factors": [{"key": k, "label": FACTORS[k], "score": factors[k], "weight": weights[k],
                               "contribution": round(factors[k] * weights[k] / 100, 1)} for k in weights],
            "status_label": STATUS[r["decision"]], "suggested_amount": r["suggested_amount"],
            "fresh_funds": r["fresh_funds"], "takeover_amount": r["takeover_amount"],
            "monthly_payment": r["monthly_payment"], "repayment_type": p["repayment_type"],
            "rate_pct": r["rate_pct"], "apr_pct": r["apr_pct"], "tenure_months": r["tenure_months"],
            "total_repayment": r["total_repayment"], "total_interest": r["total_interest"], "fees": r["fees"],
            "processing_fee_pct": p["processing_fee_pct"], "other_charges": p["other_charges"],
            "dscr_after": r["dscr_after"], "foir_after_pct": r["foir_after_pct"], "ltv_pct": r["ltv_pct"],
            "existing_emi_after": r["existing_emi_after"],
            "eligibility_fit": f"{r['passed']} of {len(r['rules'])} rules met",
            "required_changes": _changes(p, r, facts), "risks": _risks(p, r),
            "supporting_evidence": [f"{x['label']}: {x['actual']} (needs {x['required'].lower()})" for x in r["rules"]
                                    if x["status"] == "pass"][:5],
            "unresolved_conditions": [f"{x['label']}: {x['actual']}" for x in r["rules"] if x["status"] == "unresolved"]
            + [f"Document needed: {d}" for d in r["missing_documents"]],
            "exclusions": p["exclusions"], "notes": r["notes"], "turnaround_days": p["turnaround_days"],
            "expert_notes": [n for n in expert_notes or [] if n.get("product_id") in (None, "", p["id"])
                             and n.get("lender_name") in (None, "", p["lender_name"])],
            "historical_outcomes": None if not hist else {
                **hist, "label": f"{hist['offers']} of {hist['similar_cases']} similar synthetic cases reached an offer",
                "note": "Synthetic history for demonstration. Not a prediction."},
            "ai_commentary": None, "simulated_status": r["simulated_status"],
        })
    options.sort(key=lambda o: (-o["score"], o["apr_pct"] or 99, o["product_id"]))   # fully deterministic order
    for i, option in enumerate(options, 1):
        option["rank"] = i

    recovery = None
    if not options:
        reasons: dict[str, int] = {}
        for u in unsuitable:
            reasons[u["decision_label"]] = reasons.get(u["decision_label"], 0) + 1
        steps = []
        if reasons.get("Existing liabilities too high") or reasons.get("Cash flow insufficient"):
            steps.append("Restructure or consolidate existing loans to free monthly cash, then re-check the options.")
            steps.append("Test a smaller amount or a longer tenure on the restructuring page.")
        if reasons.get("Collateral requirement not satisfied"):
            steps.append("Consider whether any security (gold, property, machinery, a fixed deposit) could be offered.")
        if reasons.get("Application rejected"):
            steps.append("Some rules cannot be met yet (for example business age or recent EMI returns). "
                         "A clean repayment record over the next months changes this.")
        if reasons.get("Additional documentation required"):
            steps.append("Prepare the missing documents listed on the diagnosis page.")
        steps.append("Ask a LoanKart advisor to review the case; the full investigation goes with it.")
        recovery = {"headline": "No simulated lender fits this case as it stands.",
                    "blocking_reasons": [{"reason": k, "products": v} for k, v in sorted(reasons.items(), key=lambda x: -x[1])],
                    "steps": steps}

    return {
        "priority": priority, "priority_label": PRIORITY_LABELS[priority],
        "ranking": {"basis": "Each viable option gets a score from 0 to 100: a weighted sum of six disclosed factors. "
                             "No lender pays to be ranked and no option is hidden.",
                    "factors": [{"key": k, "label": FACTORS[k], "weight": weights[k]} for k in weights],
                    "minimum_coverage_pct": MIN_COVERAGE_PCT},
        "requested_amount": facts["requested_amount"], "tenure_months": facts["tenure_months"],
        "lenders_evaluated": len({p["lender_id"] for p in products}), "products_evaluated": len(products),
        "options": options, "unsuitable": unsuitable, "recovery_plan": recovery,
        "labels": {"indicative_match": "Indicative match: fits the simulated rules on current evidence.",
                   "illustrative_estimate": "Illustrative estimate: EMI, APR and totals calculated by LoanKart, not quoted by a lender.",
                   "simulated_offer": "Simulated lender offer: produced later by the lender simulator after a simulated application.",
                   "actual_offer": "Actual lender offer: none exist in this demo.",
                   "actual_sanction": "Actual sanction: none exist in this demo."},
    }
