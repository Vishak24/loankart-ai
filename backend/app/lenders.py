"""Lender catalogue and deterministic lender decision simulator.

Policies live in data/lenders.json (seeded into the lender_products table, editable there). They are fictional.
`evaluate` is pure: the same product and facts always give the same decision. No LLM is involved in a decision.
"""

import json
from pathlib import Path
from typing import Any

from . import calculations as calc
from .analysis import rs

CATALOGUE_PATH = Path(__file__).parent / "data" / "lenders.json"
SIMULATED = "Simulated decision from the LoanKart lender simulator using fictional rules. Not a real lender response."

DECISIONS = {
    "eligible": "Eligible for further consideration",
    "additional_documents_required": "Additional documentation required",
    "requested_amount_too_high": "Requested amount too high",
    "existing_liabilities_too_high": "Existing liabilities too high",
    "cash_flow_insufficient": "Cash flow insufficient",
    "collateral_not_satisfied": "Collateral requirement not satisfied",
    "application_rejected": "Application rejected",
    "alternative_amount_offered": "Alternative amount offered",
    "clarification_required": "Further clarification required",
}
VIABLE = {"eligible", "alternative_amount_offered", "additional_documents_required", "clarification_required"}
DOC_LABELS = {
    "bank_statement": "12 months of bank statements", "itr": "Income-tax returns for two years",
    "gstr3b": "GST returns (GSTR-3B)", "pnl": "Profit and loss account", "balance_sheet": "Balance sheet",
    "cash_flow": "Cash-flow statement", "udyam_certificate": "Udyam registration certificate",
    "collateral_valuation": "Valuation report for the security", "loan_statement": "Existing loan statements",
}
INCOME_LABELS = {"banking": "bank-statement surplus", "itr": "ITR net income", "gst": "a share of GST turnover"}


def load_catalogue() -> dict[str, Any]:
    raw = json.loads(CATALOGUE_PATH.read_text())
    lenders = {entry["id"]: entry for entry in raw["lenders"]}
    products = []
    for item in raw["products"]:
        lender = lenders[item["lender_id"]]
        products.append({**raw["defaults"], **item, "lender_name": f"{lender['name']} (fictional)",
                         "lender_type": lender["type"]})
    return {"products": products, "history": raw["synthetic_history"]}


def _principal(room: int, product: dict[str, Any], tenure: int) -> int:
    if product["repayment_type"] == "interest_only":
        return int(room * 1200 / product["interest_rate_pct"])
    return calc.principal_for_emi(room, product["interest_rate_pct"], tenure)


def terms(product: dict[str, Any], amount: int, tenure: int) -> dict[str, Any]:
    """Cost of borrowing `amount` on this product. All figures from calculations.py."""
    rate, interest_only = product["interest_rate_pct"], product["repayment_type"] == "interest_only"
    fees = calc.rupees(amount * product["processing_fee_pct"] / 100) + product["other_charges"]
    if interest_only:
        payment = calc.interest_only_payment(amount, rate)
        total = amount + payment * tenure
    else:
        cost = calc.loan_cost(amount, rate, tenure)
        payment, total = cost["emi"], cost["total_repayment"]
    return {"monthly_payment": payment, "fees": fees, "total_repayment": total, "total_interest": total - amount,
            "apr_pct": calc.apr(amount, rate, tenure, fees, interest_only=interest_only)}


def evaluate(product: dict[str, Any], facts: dict[str, Any]) -> dict[str, Any]:
    p, rules, notes = product, [], []

    def check(key: str, label: str, required: str, actual: Any, shown: str, ok: bool) -> str:
        status = "unresolved" if actual is None else ("pass" if ok else "fail")
        rules.append({"rule": key, "label": label, "required": required,
                      "actual": "Not available" if actual is None else shown, "status": status})
        return status

    takeover = facts["takeover"] if p["allows_balance_transfer"] else {"amount": 0, "emi": 0, "count": 0}
    if facts["takeover"]["amount"] and not p["allows_balance_transfer"]:
        notes.append("This product does not take over existing loans, so it is assessed without consolidation.")
    existing_emi = facts["existing_emi"] - takeover["emi"]
    requested = facts["requested_amount"] + takeover["amount"]
    tenure = min(max(facts["tenure_months"], p["min_tenure_months"]), p["max_tenure_months"])
    if tenure != facts["tenure_months"]:
        notes.append(f"Tenure adjusted to {tenure} months, the nearest this product allows.")
    surplus, revenue = facts["operating_surplus"], facts["monthly_revenue"]

    # 1. eligibility conditions (a failure here is a rejection)
    hard = [check("vintage", "Minimum age of business", f"{p['min_vintage_years']:g} years", facts["vintage_years"],
                  f"{facts['vintage_years']} years", (facts["vintage_years"] or 0) >= p["min_vintage_years"])]
    if p["min_monthly_revenue"]:
        hard.append(check("revenue", "Minimum monthly sales (documented)", rs(p["min_monthly_revenue"]), revenue,
                          rs(revenue or 0), (revenue or 0) >= p["min_monthly_revenue"]))
    if p["gst_required"]:
        hard.append(check("gst", "GST registration with returns", "Required", facts["gst_registered"],
                          "Returns on file" if facts["gst_registered"] else "No GST returns", facts["gst_registered"]))
    hard.append(check("bounces", "EMI returns in the last 12 months", f"At most {p['max_bounces_12m']}",
                      facts["emi_returns_12m"], str(facts["emi_returns_12m"]),
                      facts["emi_returns_12m"] <= p["max_bounces_12m"]))
    if facts["gst_registered"]:
        hard.append(check("late_gst", "Late GST filings in the last 12 months", f"At most {p['max_late_gst_filings']}",
                          facts["late_gst_filings"], str(facts["late_gst_filings"]),
                          facts["late_gst_filings"] <= p["max_late_gst_filings"]))
    loans = facts["active_loans"] - takeover["count"]
    hard.append(check("active_loans", "Running loans", f"At most {p['max_active_loans']}", loans, str(loans),
                      loans <= p["max_active_loans"]))
    if p["allowed_purposes"]:
        hard.append(check("purpose", "Purpose of the loan", "Machinery or equipment purchase", facts["purpose"],
                          facts["purpose"].replace("_", " "), facts["purpose"] in p["allowed_purposes"]))

    # 2. collateral
    collateral_status, ltv_cap = "pass", None
    if p["collateral_required"]:
        col = facts["collateral"] if facts["collateral_offered"] else None
        accepted = ", ".join(c.replace("_", " ") for c in p["collateral_accepted"])
        if not col or col["type"] not in p["collateral_accepted"]:
            shown = "No security offered" if not col else f"{col['type'].replace('_', ' ')} (not accepted)"
            collateral_status = check("collateral", "Security", f"One of: {accepted}", shown, shown, False)
        elif not col["value"]:
            collateral_status = check("collateral", "Security", f"One of: {accepted}, with a valuation", None, "", False)
        else:
            check("collateral", "Security", f"One of: {accepted}", col["type"],
                  f"{col['type'].replace('_', ' ')} valued at {rs(col['value'])}", True)
            ltv_cap = int(col["value"] * p["max_ltv_pct"] / 100)

    # 3. income as this lender assesses it
    income = {"banking": surplus, "itr": facts["itr_monthly_income"],
              "gst": None if not facts["gst_monthly_turnover"] or not p["gst_margin_pct"]
              else round(facts["gst_monthly_turnover"] * p["gst_margin_pct"] / 100)}[p["income_method"]]
    if income is not None and facts["co_applicant_income"] and p["allows_co_applicant"]:
        income += facts["co_applicant_income"]
        notes.append(f"Includes co-applicant income of {rs(facts['co_applicant_income'])}; proof of that income is required.")

    # 4. how much this product can support
    caps: dict[str, int] = {"product": p["max_amount"]}
    if p["turnover_multiple"] and revenue:
        caps["turnover"] = int(revenue * p["turnover_multiple"])
    if ltv_cap is not None:
        caps["ltv"] = ltv_cap
    foir_room = None
    if p["max_foir_pct"] and income is not None:
        foir_room = calc.repayment_capacity(max(income, 0), p["max_foir_pct"], existing_emi)
        caps["foir"] = _principal(foir_room, p, tenure)
    if surplus is not None:
        caps["dscr"] = _principal(calc.max_service_for_dscr(surplus, p["min_dscr"], existing_emi), p, tenure)
    binding = min(caps, key=lambda k: caps[k])
    max_supported = caps[binding] // 10_000 * 10_000

    at = terms(p, requested, tenure)
    service = existing_emi + at["monthly_payment"]
    if p["max_foir_pct"]:
        value = calc.foir(service, income) if income and income > 0 else None
        check("foir", f"Obligations to income (FOIR), income from {INCOME_LABELS[p['income_method']]}",
              f"At most {p['max_foir_pct']}%", value, f"{value}%", value is not None and value <= p["max_foir_pct"])
    cover = calc.dscr(surplus, service) if surplus is not None else None
    check("dscr", "Cash-flow cover (DSCR)", f"At least {p['min_dscr']}x", cover, f"{cover}x",
          cover is not None and cover >= p["min_dscr"])
    if "turnover" in caps:
        check("turnover_multiple", "Loan size against monthly sales", f"At most {p['turnover_multiple']:g}x monthly sales "
              f"({rs(caps['turnover'])})", requested, rs(requested), requested <= caps["turnover"])
    if ltv_cap is not None:
        value = calc.ltv(requested, facts["collateral"]["value"])
        check("ltv", "Loan to value", f"At most {p['max_ltv_pct']}%", value, f"{value}%", value <= p["max_ltv_pct"])
    check("amount_range", "Product amount range", f"{rs(p['min_amount'])} to {rs(p['max_amount'])}", requested,
          rs(requested), p["min_amount"] <= requested <= p["max_amount"])
    missing = [d for d in p["required_documents"] if d not in facts["documents"]]
    check("documents", "Required documents", f"{len(p['required_documents'])} document types", len(missing),
          "All on file" if not missing else "Missing: " + ", ".join(DOC_LABELS[d] for d in missing), not missing)
    if facts["open_clarifications"]:
        rules.append({"rule": "clarifications", "label": "Open questions on the case", "required": "None open",
                      "actual": f"{facts['open_clarifications']} unanswered", "status": "unresolved"})

    # 5. decision, in a fixed order of precedence
    income_unknown = p["max_foir_pct"] and income is None
    amount: int | None = requested
    if "fail" in hard:
        failed = [r["label"] for r in rules if r["status"] == "fail" and r["rule"] in
                  ("vintage", "revenue", "gst", "bounces", "late_gst", "active_loans", "purpose")]
        decision, amount = "application_rejected", None
        why = "Does not meet: " + "; ".join(failed) + "."
    elif collateral_status == "fail":
        decision, amount, why = "collateral_not_satisfied", None, "The security this product needs is not available or not offered."
    elif collateral_status == "unresolved":
        decision, amount, why = "clarification_required", None, "The security needs a valuation before the amount can be assessed."
    elif income_unknown or surplus is None:
        decision, amount = "additional_documents_required", None
        why = f"This lender assesses income from {INCOME_LABELS[p['income_method']]}, which is not on file."
    elif max_supported < p["min_amount"] or max_supported <= takeover["amount"]:
        amount = None
        if binding == "foir" and foir_room == 0:
            decision, why = "existing_liabilities_too_high", ("Existing EMIs already use all the room this lender's "
                                                               "income rule allows.")
        elif binding in ("foir", "dscr"):
            decision, why = "cash_flow_insufficient", ("Cash flow supports at most " + rs(max_supported)
                                                        + f", below this product's minimum of {rs(p['min_amount'])}.")
        elif binding == "ltv":
            decision, why = "collateral_not_satisfied", (f"The security supports at most {rs(max_supported)}, below "
                                                          f"this product's minimum of {rs(p['min_amount'])}.")
        else:
            decision, why = "requested_amount_too_high", f"The product supports at most {rs(max_supported)} here."
    elif requested > max_supported:
        reason = {"product": "the product maximum", "turnover": "the sales multiple", "ltv": "the loan-to-value limit",
                  "foir": "the income rule (FOIR)", "dscr": "the cash-flow cover rule (DSCR)"}[binding]
        if p["counter_offers"]:
            decision, amount = "alternative_amount_offered", max_supported
            why = f"{rs(requested)} is above what {reason} allows. Up to {rs(max_supported)} fits."
        else:
            decision, amount = "requested_amount_too_high", None
            why = f"{rs(requested)} is above what {reason} allows ({rs(max_supported)}). This lender does not counter-offer."
    elif requested < p["min_amount"]:
        decision, amount, why = "requested_amount_too_high", None, f"Below this product's minimum of {rs(p['min_amount'])}."
    elif missing:
        decision, why = "additional_documents_required", "Fits on the figures; documents are still needed."
    elif facts["open_clarifications"] or any(r["status"] == "unresolved" for r in rules):
        decision, why = "clarification_required", "Fits on the figures; open questions must be answered first."
    else:
        decision, why = "eligible", "Meets every rule in this simulated policy at the requested amount."

    result: dict[str, Any] = {
        "product_id": p["id"], "decision": decision, "decision_label": DECISIONS[decision], "explanation": why,
        "rules": rules, "passed": sum(r["status"] == "pass" for r in rules),
        "failed": sum(r["status"] == "fail" for r in rules), "unresolved": sum(r["status"] == "unresolved" for r in rules),
        "requested_amount": requested, "max_supported_amount": max_supported, "suggested_amount": amount,
        "fresh_funds": None, "takeover_amount": takeover["amount"], "tenure_months": tenure,
        "rate_pct": p["interest_rate_pct"], "repayment_type": p["repayment_type"], "monthly_payment": None, "fees": None,
        "total_repayment": None, "total_interest": None, "apr_pct": None, "dscr_after": None, "foir_after_pct": None,
        "ltv_pct": None, "existing_emi_after": existing_emi, "missing_documents": [DOC_LABELS[d] for d in missing],
        "notes": notes, "simulated_status": SIMULATED,
    }
    if amount:
        t = terms(p, amount, tenure)
        service = existing_emi + t["monthly_payment"]
        result.update(t, fresh_funds=amount - takeover["amount"], dscr_after=calc.dscr(surplus, service),
                      foir_after_pct=calc.foir(service, income) if income and income > 0 else None,
                      ltv_pct=calc.ltv(amount, facts["collateral"]["value"]) if ltv_cap is not None else None)
    return result
