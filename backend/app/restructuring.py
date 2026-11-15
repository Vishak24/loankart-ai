"""Restructuring engine: the eight dimensions, each with before/after figures from calculations.py.

Nothing here is applied automatically. `apply` turns the borrower's chosen scenario into the facts a lender would
see; `dimensions` describes what each lever would do, its costs and risks, and how many simulated lender products
it would open up. No option involves changing or inventing documents.
"""

from typing import Any

from . import calculations as calc
from .analysis import ILLUSTRATIVE_RATE, rs
from .lenders import VIABLE, evaluate

REFINANCE_FEE_PCT = 1.0          # illustrative foreclosure / processing cost of moving a loan
DSCR_COMFORT = 1.2               # illustration only; each lender applies its own minimum
CATEGORY_LABELS = {
    "working_capital": "Working-capital line", "term_loan": "Business term loan", "lap": "Loan against property",
    "secured_business": "Secured business loan", "unsecured_business": "Unsecured business loan",
    "equipment": "Equipment finance",
}


def default_inputs(profile: dict[str, Any]) -> dict[str, Any]:
    return {"amount": profile["requested_amount"], "tenure_months": 36, "liability_actions": {},
            "offer_collateral": profile["collateral"] != "none", "product_categories": [],
            "co_applicant_income": 0, "include_paytm_evidence": False}


def _refinance_terms(loan: dict[str, Any], action: dict[str, Any]) -> tuple[float, int]:
    rate = action.get("rate") or min(loan["rate"] or 18.0, 17.0)
    return rate, action.get("tenure") or 48


def apply(inputs: dict[str, Any], base: dict[str, Any], obligations: list[dict[str, Any]]) -> dict[str, Any]:
    """Facts as they would stand under the chosen scenario."""
    facts = {**base, "requested_amount": inputs["amount"], "tenure_months": inputs["tenure_months"],
             "collateral_offered": bool(base["collateral"]) and inputs["offer_collateral"],
             "co_applicant_income": inputs["co_applicant_income"],
             "supplementary_evidence": ["paytm"] if inputs["include_paytm_evidence"] else [],
             "takeover": {"amount": 0, "emi": 0, "count": 0}}
    for loan in obligations:
        action = inputs["liability_actions"].get(loan["account_no"], {"action": "keep"})
        if loan["status"] != "active" or not loan["outstanding"]:
            continue
        if action["action"] == "refinance":
            rate, tenure = _refinance_terms(loan, action)
            facts["existing_emi"] += calc.emi(loan["outstanding"], rate, tenure) - loan["emi"]
        elif action["action"] == "consolidate":
            facts["takeover"] = {"amount": facts["takeover"]["amount"] + loan["outstanding"],
                                 "emi": facts["takeover"]["emi"] + loan["emi"], "count": facts["takeover"]["count"] + 1}
    return facts


def position(facts: dict[str, Any], products: list[dict[str, Any]]) -> dict[str, Any]:
    """One side of the before/after comparison, at illustrative terms, plus the simulated lender fit."""
    existing = facts["existing_emi"] - facts["takeover"]["emi"]
    amount = facts["requested_amount"] + facts["takeover"]["amount"]
    cost = calc.loan_cost(amount, ILLUSTRATIVE_RATE, facts["tenure_months"])
    results = [evaluate(p, facts) for p in products]
    viable = [r for r in results if r["decision"] in VIABLE]
    return {
        "fresh_funds": facts["requested_amount"], "loan_amount": amount, "tenure_months": facts["tenure_months"],
        "existing_emi": existing, "new_emi": cost["emi"], "total_monthly_repayment": existing + cost["emi"],
        "total_repayment": cost["total_repayment"], "total_interest": cost["total_interest"],
        "operating_surplus": facts["operating_surplus"],
        "free_cash_after": facts["operating_surplus"] - existing - cost["emi"],
        "dscr": calc.dscr(facts["operating_surplus"], existing + cost["emi"]),
        "illustrative_rate_pct": ILLUSTRATIVE_RATE,
        "products_fitting_in_full": sum(r["decision"] == "eligible" or (r["decision"] in VIABLE and r["suggested_amount"] == r["requested_amount"]) for r in results),
        "products_viable": len(viable), "products_evaluated": len(results),
        "best_fresh_funds": max((r["fresh_funds"] or 0 for r in viable), default=0),
    }


def _fit(facts: dict[str, Any], products: list[dict[str, Any]]) -> tuple[int, str]:
    results = [(p, evaluate(p, facts)) for p in products]
    viable = [(p, r) for p, r in results if r["decision"] in VIABLE]
    if not viable:
        return 0, "No simulated product is viable with this change alone."
    p, r = max(viable, key=lambda x: x[1]["fresh_funds"] or 0)
    return len(viable), (f"{p['lender_name']} {p['product_name']}: {r['decision_label'].lower()}, "
                         f"{rs(r['fresh_funds'])} of fresh funds (simulated).")


def dimensions(inputs: dict[str, Any], base: dict[str, Any], analysis: dict[str, Any], profile: dict[str, Any],
               products: list[dict[str, Any]], paytm: dict[str, Any] | None) -> list[dict[str, Any]]:
    m, obligations = analysis["metrics"], analysis["obligations"]
    neutral = default_inputs(profile)
    base_fit = _fit(apply(neutral, base, obligations), products)[0]
    surplus, existing, requested = m["avg_operating_surplus"], m["existing_emi"], profile["requested_amount"]
    active = [o for o in obligations if o["status"] == "active" and o["outstanding"]]
    out: list[dict[str, Any]] = []

    def add(key: str, title: str, relevant: bool, why: str, current: str, proposed: str, impact: str,
            emi_impact: int | None, total_impact: int | None, costs: list[str], risks: list[str],
            evidence: list[str], change: dict[str, Any] | None, options: list[dict[str, Any]],
            applied: bool) -> None:
        fit, example = _fit(apply({**neutral, **change}, base, obligations), products) if change else (base_fit, "")
        out.append({"key": key, "title": title, "relevant": relevant, "why": why, "current": current,
                    "proposed": proposed, "financial_impact": impact, "emi_impact": emi_impact,
                    "total_repayment_impact": total_impact, "additional_costs": costs, "risks": risks,
                    "required_evidence": evidence, "lender_fit_before": base_fit, "lender_fit_after": fit,
                    "lender_fit_example": example, "options": options, "applied": applied})

    # 1. loan amount
    room = calc.max_service_for_dscr(surplus, DSCR_COMFORT, existing)
    supported = calc.principal_for_emi(room, ILLUSTRATIVE_RATE, 36) // 10_000 * 10_000
    base_cost = calc.loan_cost(requested, ILLUSTRATIVE_RATE, 36)
    amounts = sorted({requested, requested * 3 // 4 // 10_000 * 10_000, requested // 2 // 10_000 * 10_000,
                      max(supported, 50_000)}, reverse=True)
    rows = []
    for a in amounts:
        c = calc.loan_cost(a, ILLUSTRATIVE_RATE, 36)
        rows.append({"label": rs(a), "amount": a, "emi": c["emi"], "total_repayment": c["total_repayment"],
                     "dscr": calc.dscr(surplus, existing + c["emi"])})
    low = calc.loan_cost(max(supported, 50_000), ILLUSTRATIVE_RATE, 36)
    add("amount", "Loan amount", requested > supported,
        f"Documented cash flow comfortably carries about {rs(supported)} at illustrative terms; you asked for {rs(requested)}.",
        f"{rs(requested)} requested (EMI about {rs(base_cost['emi'])})",
        f"About {rs(max(supported, 50_000))} (EMI about {rs(low['emi'])})",
        "A smaller loan lowers the EMI and the total repaid, but covers less of the need.",
        low["emi"] - base_cost["emi"], low["total_repayment"] - base_cost["total_repayment"], [],
        ["The business may still be short of working capital."], [],
        {"amount": max(supported, 50_000)}, rows, inputs["amount"] != requested)

    # 2. tenure
    rows = []
    for t in (24, 36, 48, 60):
        c = calc.loan_cost(inputs["amount"], ILLUSTRATIVE_RATE, t)
        rows.append({"label": f"{t} months", "tenure_months": t, "emi": c["emi"], "total_interest": c["total_interest"],
                     "total_repayment": c["total_repayment"], "dscr": calc.dscr(surplus, existing + c["emi"])})
    c36, c60 = calc.loan_cost(requested, ILLUSTRATIVE_RATE, 36), calc.loan_cost(requested, ILLUSTRATIVE_RATE, 60)
    add("tenure", "Tenure", True, "A longer tenure lowers the EMI and raises the total interest. Both are shown together.",
        f"36 months: EMI {rs(c36['emi'])}, interest {rs(c36['total_interest'])}",
        f"60 months: EMI {rs(c60['emi'])}, interest {rs(c60['total_interest'])}",
        f"EMI falls by {rs(c36['emi'] - c60['emi'])}; total interest rises by {rs(c60['total_interest'] - c36['total_interest'])}.",
        c60["emi"] - c36["emi"], c60["total_repayment"] - c36["total_repayment"], [],
        ["You pay interest for longer.", "Not every product offers 60 months."], [],
        {"tenure_months": 60}, rows, inputs["tenure_months"] != 36)

    # 3. existing liabilities
    rows, relief_total, extra_total = [], 0, 0
    for o in active:
        rate, tenure = _refinance_terms(o, inputs["liability_actions"].get(o["account_no"], {}))
        r = calc.refinance(o["outstanding"], rate, tenure, o["emi"], o["remaining_months"] or 1, REFINANCE_FEE_PCT)
        chosen = inputs["liability_actions"].get(o["account_no"], {}).get("action", "keep")
        rows.append({"label": f"{o['lender']} {o['product']}", "account_no": o["account_no"], "emi": o["emi"],
                     "outstanding": o["outstanding"], "remaining_months": o["remaining_months"], "rate": o["rate"],
                     "new_rate": rate, "new_tenure": tenure, "new_emi": r["new_emi"],
                     "monthly_relief": r["monthly_relief"], "extra_cost": r["extra_cost"], "action": chosen})
        relief_total, extra_total = relief_total + max(r["monthly_relief"], 0), extra_total + r["extra_cost"]
    costly = max(active, key=lambda o: o["rate"] or 0) if active else None
    add("liabilities", "Existing loans", bool(active) and surplus > 0 and existing / surplus > 0.4,
        "Existing EMIs take a large share of the monthly surplus." if active else "No running loans were found.",
        f"{len(active)} loan(s), {rs(existing)} a month" if active else "No existing EMIs",
        "Refinance over a longer period, or fold a costly loan into the new one" if active else "Nothing to change",
        f"Spreading all of them over 48 months would free about {rs(relief_total)} a month and cost about "
        f"{rs(extra_total)} more in total." if active else "",
        -relief_total if active else None, extra_total if active else None,
        [f"Illustrative {REFINANCE_FEE_PCT:g}% closure/processing cost on the amount moved"] if active else [],
        ["Lower EMI now, more interest overall.", "The current lender may charge foreclosure fees.",
         "Needs a lender willing to take the loan over."] if active else [],
        ["Latest statement and foreclosure letter for each loan moved"] if active else [],
        {"liability_actions": {costly["account_no"]: {"action": "consolidate"}}} if costly else None, rows,
        any(a.get("action", "keep") != "keep" for a in inputs["liability_actions"].values()))

    # 4. collateral / security
    col = base["collateral"]
    secured = [p for p in products if p["collateral_required"] and col and col["type"] in p["collateral_accepted"]]
    rows = [{"label": f"{p['lender_name']} {p['product_name']}", "max_ltv_pct": p["max_ltv_pct"],
             "amount": int((col["value"] or 0) * p["max_ltv_pct"] / 100), "rate": p["interest_rate_pct"]} for p in secured]
    add("collateral", "Security", bool(col),
        f"You said you could offer {col['type'].replace('_', ' ')}." if col else "No security was declared.",
        ("Offered" if inputs["offer_collateral"] else "Not offered") if col else "None",
        f"Offer {col['type'].replace('_', ' ')} valued at {rs(col['value'] or 0)}" if col else "Not applicable",
        f"{len(secured)} simulated secured product(s) accept it, lending up to "
        f"{rs(max((r['amount'] for r in rows), default=0))} at lower rates than unsecured loans." if col else "",
        None, None, ["Valuation, appraisal and documentation charges"] if col else [],
        ["If repayments are missed the lender can sell the asset.", "The asset is locked until the loan is closed."] if col else [],
        ["Valuation report", "Proof of ownership"] if col else [],
        {"offer_collateral": False} if col else None, rows, bool(col) and not inputs["offer_collateral"])
    if col:   # the lever on this card is withdrawing security, so show the fit with it offered as "after"
        out[-1]["lender_fit_before"], out[-1]["lender_fit_after"] = out[-1]["lender_fit_after"], base_fit

    # 5. loan product
    rows = []
    facts_now = apply(inputs, base, obligations)
    for category, label in CATEGORY_LABELS.items():
        results = [(p, evaluate(p, facts_now)) for p in products if p["category"] == category]
        viable = [(p, r) for p, r in results if r["decision"] in VIABLE]
        best = max(viable, key=lambda x: x[1]["fresh_funds"] or 0, default=None)
        rows.append({"label": label, "category": category, "products": len(results), "viable": len(viable),
                     "best_fresh_funds": best[1]["fresh_funds"] if best else None,
                     "monthly_payment": best[1]["monthly_payment"] if best else None,
                     "repayment_type": best[0]["repayment_type"] if best else None})
    io = calc.interest_only_payment(requested, 14)
    add("product", "Type of loan", True,
        "The same need can be met by an EMI loan, an interest-only credit line or a secured loan, with very different monthly cost.",
        f"EMI term loan: about {rs(base_cost['emi'])} a month", f"Interest-only credit line: about {rs(io)} a month at 14%",
        "An interest-only line costs far less each month because the principal is not repaid monthly.",
        io - base_cost["emi"], None, ["Annual renewal fees on credit lines"],
        ["The whole limit falls due if the line is not renewed.", "Interest is charged for as long as the money is drawn."],
        [], None, rows, bool(inputs["product_categories"]))

    # 6. income and cash-flow evidence
    rows = [{"label": h["label"], "value": h["value"], "state": h["state"]} for h in analysis["headline"]
            if h["key"] in ("declared_monthly_revenue", "avg_business_receipts", "avg_gst_turnover")]
    if paytm:
        rows.append({"label": "Paytm net settlements, monthly average (synthetic fixture)",
                     "value": paytm["avg_net_settlements"], "state": "simulated"})
    gap = m["declared_vs_bank_gap_pct"] or 0
    add("evidence", "Income and cash-flow evidence", gap > 15 or m["cash_share_pct"] > 30,
        "Lenders use documented income. The aim is to evidence what is real, never to change the figures.",
        f"Documented sales {rs(m['avg_business_receipts'])} a month; {m['cash_share_pct']}% arrives as cash",
        "Add payment-gateway settlement records as supporting evidence" if paytm else "Add sales registers or payment records",
        "Does not change any calculated figure. It makes existing receipts easier for a lender to trace.",
        None, None, [], ["Collections through one channel are not total revenue and are never treated as such."],
        ["Merchant consent to share payment and settlement data"], {"include_paytm_evidence": True} if paytm else None,
        rows, inputs["include_paytm_evidence"])

    # 7. borrower / financing structure
    itr_products = [p for p in products if p["income_method"] == "itr"]
    add("structure", "Co-applicant or guarantor", bool(m["itr_net_annual"]) and existing > 0.5 * (m["itr_net_annual"] / 12),
        "Lenders that assess from the ITR see income that is small next to existing EMIs. An eligible co-applicant's "
        "documented income can be added." if m["itr_net_annual"] else "No ITR income is on file.",
        f"Single applicant, ITR income {rs(round((m['itr_net_annual'] or 0) / 12))} a month",
        "Add a co-applicant with documented income (for example a spouse with a salary)",
        f"Affects the {len(itr_products)} simulated product(s) that assess from ITR income.", None, None, [],
        ["The co-applicant is fully liable for the loan.", "Their credit record is affected by any missed payment."],
        ["Co-applicant's identity proof, income proof and consent"], {"co_applicant_income": 40_000}, [],
        inputs["co_applicant_income"] > 0)

    # 8. documentation and reconciliation
    open_items = [{"label": d["label"], "kind": "document", "detail": d["reason"]} for d in analysis["missing_documents"]]
    open_items += [{"label": c["question"], "kind": "question", "detail": c["why"]} for c in analysis["clarifications"]
                   if not c["answer"] or c["answer"] == "not_sure"]
    if m["emi_returns_12m"]:
        open_items.append({"label": "Written explanation for the returned EMI", "kind": "explanation",
                           "detail": "Lenders usually ask about it."})
    if m["late_gst_filings"]:
        open_items.append({"label": "Explanation for late GST filings", "kind": "explanation", "detail": "Shows it was a one-off."})
    resolved = {**base, "open_clarifications": 0}
    fit, example = _fit(apply(neutral, resolved, obligations), products)
    add("documentation", "Documents and reconciliation", bool(open_items), f"{len(open_items)} item(s) are open.",
        f"{len(analysis['missing_documents'])} document(s) missing, {base['open_clarifications']} question(s) open",
        "Close the open items with genuine documents and answers",
        "Removes conditions from otherwise viable products. It does not change any figure.", None, None, [],
        ["Only real documents count. LoanKart will not help alter or create records."], [i["label"] for i in open_items],
        None, open_items, False)
    out[-1]["lender_fit_after"], out[-1]["lender_fit_example"] = fit, example
    return out


def compute(inputs: dict[str, Any], base: dict[str, Any], analysis: dict[str, Any], profile: dict[str, Any],
            products: list[dict[str, Any]], paytm: dict[str, Any] | None) -> dict[str, Any]:
    obligations = analysis["obligations"]
    current = position(apply(default_inputs(profile), base, obligations), products)
    proposed = position(apply(inputs, base, obligations), products)
    notes = []
    for loan in obligations:
        action = inputs["liability_actions"].get(loan["account_no"], {}).get("action", "keep")
        if action == "refinance" and loan["outstanding"]:
            rate, tenure = _refinance_terms(loan, inputs["liability_actions"][loan["account_no"]])
            r = calc.refinance(loan["outstanding"], rate, tenure, loan["emi"], loan["remaining_months"] or 1, REFINANCE_FEE_PCT)
            notes.append(f"Refinancing {loan['lender']} at an illustrative {rate:g}% over {tenure} months frees "
                         f"{rs(r['monthly_relief'])} a month and costs {rs(r['extra_cost'])} more in total.")
        elif action == "consolidate" and loan["outstanding"]:
            notes.append(f"{rs(loan['outstanding'])} owed to {loan['lender']} is folded into the new loan; its EMI of "
                         f"{rs(loan['emi'])} stops. Only products that take over loans can do this.")
    return {"inputs": inputs, "current": current, "proposed": proposed, "notes": notes,
            "dimensions": dimensions(inputs, base, analysis, profile, products, paytm),
            "assumptions": [
                f"EMIs here use an illustrative {ILLUSTRATIVE_RATE:g}% a year so scenarios can be compared like for like. "
                "Each lender's own rate is used on the options page.",
                "Operating surplus is average sales receipts minus running costs from the bank statements.",
                f"Cash-flow cover of {DSCR_COMFORT}x is used for illustration; each simulated lender sets its own minimum.",
                "Lender fit counts come from the simulated lender rules, which are fictional."]}
