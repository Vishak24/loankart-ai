"""Layer C: financial investigation over extracted documents.

Inputs are extraction outputs (extraction.py), the borrower's own onboarding answers, and any clarifications or
advisor corrections recorded on the case. This module never sees the ground-truth dataset. Every figure is computed
here or in calculations.py; every finding carries the document references it was derived from.

Wording rule: a finding is a "potential contributing factor" unless a supplied document states it outright.
"""

import re
from collections import Counter
from typing import Any

from . import calculations as calc

# Used only to illustrate what the requested loan would cost. Not any lender's terms.
ILLUSTRATIVE_RATE, ILLUSTRATIVE_TENURE = 18.0, 36

CREDIT_ANSWERS = {"business_receipt": "A customer payment for sales", "owner_contribution": "My own or family money",
                  "loan_disbursement": "Borrowed money I have to repay", "not_sure": "I'm not sure"}
OPEX_PREFIXES = ("GST PMT", "RENT", "EB BILL", "FREIGHT", "SALARY")
BORROWER_CORRECTABLE = {"collateral_value"}
ADVISOR_CORRECTABLE = {"avg_business_receipts", "avg_operating_expenses", "existing_emi", "collateral_value",
                       "emi_returns_12m", "late_gst_filings"}


def rs(n: int | float) -> str:
    """₹ with Indian digit grouping."""
    s = str(abs(int(round(n))))
    head, tail = s[:-3], s[-3:]
    groups = []
    while len(head) > 2:
        groups.insert(0, head[-2:])
        head = head[:-2]
    if head:
        groups.insert(0, head)
    return ("-" if n < 0 else "") + "₹" + ",".join(groups + [tail])


def classify(row: dict[str, Any]) -> tuple[str, str]:
    """(category, detail) for a bank transaction, from its narration alone."""
    n = row["narration"]
    if row["credit"]:
        if n.startswith("CASH DEP"):
            return "business_receipt", "cash"
        if n.startswith("PAYTM SETTLEMENT"):
            return "business_receipt", "paytm"
        if re.match(r"(NEFT|IMPS|UPI|RTGS) CR-.+-INV \d+$", n):
            return "business_receipt", "transfer"
        if n.startswith("TRF FROM OWN"):
            return "internal_transfer", ""
        if n.startswith("LOAN DISB"):
            return "loan_disbursement", ""
        if n.startswith("IT REFUND"):
            return "other_credit", "tax refund"
        if n.startswith("REFUND"):
            return "refund", ""
        if n.startswith("CAPITAL INTRODUCED"):
            return "owner_contribution", ""
        return "unclassified_credit", ""      # no invoice reference, no known pattern: ask, do not assume
    if n.startswith("ACH RTN CHGS"):
        return "bounce_charge", ""
    if n.startswith("ACH D-"):
        return "loan_repayment", ""
    if n.startswith("TRF TO OWN"):
        return "internal_transfer", ""
    if "SELF DRAWINGS" in n:
        return "owner_drawings", ""
    known = n.startswith(OPEX_PREFIXES) or n.endswith("-PURCHASE")
    return "operating_expense", "" if known else "unrecognised"


def _ref(doc: dict[str, Any], locator: str, value: Any) -> dict[str, str]:
    return {"document_id": doc["id"], "document_title": doc["title"], "locator": locator,
            "value": rs(value) if isinstance(value, int) else str(value)}


def _pct(a: float, b: float) -> float | None:
    return None if not b else calc.ratio((a - b) / b * 100)


def _avg(values: list[int]) -> int:
    return calc.rupees(sum(values) / len(values)) if values else 0


def analyse(docs: list[dict[str, Any]], profile: dict[str, Any], answers: dict[str, str] | None = None,
            corrections: dict[str, dict[str, Any]] | None = None) -> dict[str, Any]:
    answers, corrections = answers or {}, corrections or {}
    by_type: dict[str, list[dict[str, Any]]] = {}
    for doc in docs:
        if doc.get("extraction") and doc["extraction"].get("doc_type"):
            by_type.setdefault(doc["extraction"]["doc_type"], []).append(doc)
    fields = lambda d: d["extraction"]["fields"]  # noqa: E731

    # ---- bank statements: classify every transaction, summarise by month
    bank_docs = sorted(by_type.get("bank_statement", []), key=lambda d: fields(d)["month"] or "")
    months, unclassified, emi_series, disbursements, bounce_rows, unusual = [], [], {}, [], [], []
    asked: list[dict[str, Any]] = []      # every credit the borrower was asked about, answered or not
    counts: Counter[str] = Counter()
    for doc in bank_docs:
        tot: Counter[str] = Counter()
        for row in doc["extraction"]["rows"]:
            category, detail = classify(row)
            if category == "unclassified_credit":
                cid = f"credit-{row['ref']}"
                answer = answers.get(cid)
                asked.append({"id": cid, "row": row})
                if answer and answer != "not_sure":
                    category = answer
                else:
                    unclassified.append({"id": cid, "doc": doc, "row": row})
            value = row["credit"] or row["debit"]
            counts[category] += 1
            tot[category] += value
            if detail in ("cash", "paytm"):
                tot[detail] += value
            if category == "loan_repayment":
                m = re.match(r"^ACH D-(.+?)-(\w+?)(?:-REPRESENT)?$", row["narration"])
                key = (m.group(1), m.group(2)) if m else (row["narration"], "")
                emi_series.setdefault(key, []).append((fields(doc)["month"], value, doc, row))
            elif category == "loan_disbursement":
                disbursements.append((doc, row))
            elif category == "bounce_charge":
                bounce_rows.append((doc, row))
        receipts = tot["business_receipt"]
        for row in doc["extraction"]["rows"]:
            if row["credit"] and receipts and row["credit"] >= 0.2 * receipts and classify(row)[0] != "business_receipt":
                unusual.append({"date": row["date"], "narration": row["narration"], "amount": row["credit"],
                                "why": "Large credit that is not a recognised sales receipt",
                                "document_id": doc["id"]})
        f = fields(doc)
        months.append({
            "month": f["month"], "total_credits": f["total_credits"], "total_debits": f["total_debits"],
            "business_receipts": receipts, "cash_deposits": tot["cash"], "paytm_settlements": tot["paytm"],
            "non_business_credits": (f["total_credits"] or 0) - receipts - tot["unclassified_credit"],
            "unclassified_credits": tot["unclassified_credit"], "operating_expenses": tot["operating_expense"],
            "loan_repayments": tot["loan_repayment"], "owner_drawings": tot["owner_drawings"],
            "operating_surplus": receipts - tot["operating_expense"], "closing_balance": f["closing_balance"],
            "gst_taxable": None, "gst_gross": None, "document_id": doc["id"],
        })
    active_months = [m for m in months if m["business_receipts"] > 0]
    latest_month = months[-1]["month"] if months else None

    # ---- GST
    gst_docs = sorted(by_type.get("gstr3b", []), key=lambda d: fields(d)["month"] or "")
    gst_by_month = {fields(d)["month"]: d for d in gst_docs}
    for m in months:
        d = gst_by_month.get(m["month"])
        if d:
            m["gst_taxable"], m["gst_gross"] = fields(d)["taxable"], fields(d)["taxable"] + fields(d)["tax"]
    late_docs = [d for d in gst_docs if (fields(d)["days_late"] or 0) > 0]
    gst_months = [m for m in months if m["gst_taxable"] is not None]
    gstr1_total = sum(fields(d)["taxable"] or 0 for d in by_type.get("gstr1", []))
    gstr3b_total = sum(fields(d)["taxable"] or 0 for d in gst_docs)

    # ---- existing obligations: recurring ACH debits joined to loan statements
    loan_docs = {fields(d)["account_no"]: d for d in by_type.get("loan_statement", [])}
    obligations = []
    for (short, account), hits in emi_series.items():
        doc = loan_docs.get(account)
        emi = Counter(v for _, v, _, _ in hits).most_common(1)[0][0]
        last_seen = max(h[0] for h in hits)
        lf = fields(doc) if doc else {}
        obligations.append({
            "account_no": account, "lender": doc["extraction"]["issuer"] if doc else short,
            "product": lf.get("product") or "Loan (no statement supplied)", "emi": lf.get("emi") or emi,
            "months_seen": len({h[0] for h in hits}), "last_seen": last_seen,
            "status": "active" if (last_seen == latest_month or (lf.get("remaining") or 0) > 0) else "ended",
            "documented": bool(doc), "outstanding": lf.get("outstanding"), "remaining_months": lf.get("remaining"),
            "rate": lf.get("rate"), "secured": lf.get("security") == "Secured" if doc else None,
            "principal": lf.get("principal"), "document_id": doc["id"] if doc else hits[-1][2]["id"],
        })
    for account, doc in loan_docs.items():       # statement supplied but EMI not seen in this bank account
        if not any(o["account_no"] == account for o in obligations):
            lf = fields(doc)
            obligations.append({"account_no": account, "lender": doc["extraction"]["issuer"], "product": lf["product"],
                                "emi": lf["emi"], "months_seen": 0, "last_seen": None, "status": "active",
                                "documented": True, "outstanding": lf["outstanding"],
                                "remaining_months": lf["remaining"], "rate": lf["rate"],
                                "secured": lf["security"] == "Secured", "principal": lf["principal"],
                                "document_id": doc["id"]})
    obligations.sort(key=lambda o: (o["status"], -o["emi"]))
    active = [o for o in obligations if o["status"] == "active"]
    undocumented = [o for o in obligations if not o["documented"]]

    # ---- other documents
    itrs = sorted(by_type.get("itr", []), key=lambda d: fields(d)["ay"] or "")
    itr = itrs[-1] if itrs else None
    one = lambda t: (by_type.get(t) or [None])[0]  # noqa: E731
    pnl, bs, udyam, valuation, rejection, history = (one(t) for t in (
        "pnl", "balance_sheet", "udyam_certificate", "collateral_valuation", "rejection_letter", "repayment_history"))

    # ---- metrics
    n_active = len(active_months) or 1
    avg_receipts = _avg([m["business_receipts"] for m in active_months])
    avg_opex = _avg([m["operating_expenses"] for m in active_months])
    total_receipts = sum(m["business_receipts"] for m in months)
    late_history = fields(history)["late"] if history else 0
    vintage = None
    if udyam and fields(udyam)["commenced"] and latest_month:
        y, mo = map(int, fields(udyam)["commenced"][:7].split("-"))
        ly, lm = map(int, latest_month.split("-"))
        vintage = round(((ly - y) * 12 + lm - mo + 1) / 12, 1)
    collateral_value = fields(valuation)["value"] if valuation else None
    metrics: dict[str, Any] = {
        "months_analysed": len(months), "months_with_receipts": len(active_months),
        "avg_total_credits": _avg([m["total_credits"] or 0 for m in active_months]),
        "avg_business_receipts": avg_receipts, "avg_operating_expenses": avg_opex,
        "existing_emi": sum(o["emi"] for o in active), "active_loans": len(active),
        "outstanding_total": sum(o["outstanding"] or 0 for o in active),
        "avg_gst_turnover": _avg([m["gst_taxable"] for m in gst_months]) if gst_months else None,
        "avg_gst_gross": _avg([m["gst_gross"] for m in gst_months]) if gst_months else None,
        "itr_net_annual": fields(itr)["net_income"] if itr else None,
        "itr_gross_receipts": fields(itr)["gross_receipts"] if itr else None,
        "itr_years": len(itrs),
        "cash_share_pct": calc.ratio(sum(m["cash_deposits"] for m in months) / total_receipts * 100) if total_receipts else 0.0,
        "paytm_share_pct": calc.ratio(sum(m["paytm_settlements"] for m in months) / total_receipts * 100) if total_receipts else 0.0,
        "emi_returns_12m": max(len(bounce_rows), late_history or 0), "late_gst_filings": len(late_docs),
        "vintage_years": vintage, "collateral_value": collateral_value,
        "unclassified_credit_total": sum(u["row"]["credit"] for u in unclassified),
        "non_business_credit_total": sum(m["non_business_credits"] for m in months),
    }
    originals: dict[str, Any] = {}
    for key, c in corrections.items():           # explicit, attributed corrections; the original is kept
        if key in metrics:
            originals[key] = metrics[key]
            metrics[key] = c["value"]
    surplus = metrics["avg_business_receipts"] - metrics["avg_operating_expenses"]
    requested = profile["requested_amount"]
    new_emi = calc.emi(requested, ILLUSTRATIVE_RATE, ILLUSTRATIVE_TENURE)
    first3, last3 = active_months[:3], active_months[-3:]
    metrics.update({
        "avg_operating_surplus": surplus, "avg_free_cash": surplus - metrics["existing_emi"],
        "dscr_existing": calc.dscr(surplus, metrics["existing_emi"]),
        "illustrative_new_emi": new_emi,
        "dscr_with_requested": calc.dscr(surplus, metrics["existing_emi"] + new_emi),
        "foir_itr_existing_pct": calc.foir(metrics["existing_emi"], metrics["itr_net_annual"] / 12)
        if metrics["itr_net_annual"] else None,
        "declared_monthly_revenue": profile["monthly_revenue"],
        "declared_vs_bank_gap_pct": _pct(profile["monthly_revenue"], metrics["avg_business_receipts"]),
        "bank_vs_gst_gap_pct": _pct(sum(m["business_receipts"] for m in gst_months),
                                    sum(m["gst_gross"] for m in gst_months)) if gst_months else None,
        "revenue_trend_pct": _pct(_avg([m["business_receipts"] for m in last3]),
                                  _avg([m["business_receipts"] for m in first3])) if n_active >= 6 else None,
    })

    # ---- document checklist
    missing = []

    def need(doc_type: str, label: str, reason: str, present: bool) -> None:
        if not present:
            missing.append({"doc_type": doc_type, "label": label, "reason": reason})

    registered = profile["gst_status"] == "registered"
    need("bank_statement", "Bank statements for 12 months", "Shows actual receipts, expenses and EMIs.", len(months) >= 12)
    need("gstr3b", "GST returns (GSTR-3B)", "Supports declared turnover.", not registered or len(gst_docs) >= 6)
    need("itr", "Income-tax returns for the last two years", "Most lenders assess income from ITRs.", len(itrs) >= 2)
    need("pnl", "Profit and loss account", "Shows profitability for the last financial year.", bool(pnl))
    need("balance_sheet", "Balance sheet", "Shows assets, stock, debtors and borrowings.", bool(bs))
    need("cash_flow", "Cash-flow statement", "Shows where cash came from and went.", bool(one("cash_flow")))
    need("udyam_certificate", "Udyam / business registration proof", "Confirms the business and its start date.", bool(udyam))
    need("collateral_valuation", "Valuation of the security offered", "Needed before any secured product can be assessed.",
         profile["collateral"] == "none" or bool(valuation))
    for o in undocumented:
        if o["status"] == "active":
            need("loan_statement", f"Loan statement for {o['lender']} ({o['account_no']})",
                 "A recurring EMI is visible in the bank statement without a matching loan statement.", False)

    # ---- reconciliation table
    recon = []

    def line(item: str, a_label: str, a: Any, b_label: str, b: Any, tolerance: float, note: str = "") -> None:
        if a is None or b is None:
            status, variance = "missing", None
        else:
            variance = _pct(a, b)
            status = "matched" if variance is not None and abs(variance) <= tolerance else "variance"
        recon.append({"item": item, "source_a": a_label, "value_a": a, "source_b": b_label, "value_b": b,
                      "variance_pct": variance, "status": status, "note": note})

    line("Monthly sales: what you told us vs bank receipts", "Your answer", profile["monthly_revenue"],
         "Bank statements (business receipts)", metrics["avg_business_receipts"], 10)
    line("Bank receipts vs GST turnover incl. tax (same months)", "Bank statements",
         sum(m["business_receipts"] for m in gst_months) if gst_months else None, "GSTR-3B",
         sum(m["gst_gross"] for m in gst_months) if gst_months else None, 5,
         "Receipts include GST collected, so GST turnover is compared with tax added.")
    line("GSTR-1 vs GSTR-3B taxable value", "GSTR-1", gstr1_total or None, "GSTR-3B", gstr3b_total or None, 1)
    line("ITR gross receipts vs GST turnover (monthly average)", "Latest ITR",
         round(metrics["itr_gross_receipts"] / 12) if metrics["itr_gross_receipts"] else None, "GSTR-3B",
         metrics["avg_gst_turnover"], 12, "Different 12-month periods, so some difference is expected.")
    line("P&L revenue vs ITR gross receipts", "Profit and loss account", fields(pnl)["revenue"] if pnl else None,
         "Latest ITR", metrics["itr_gross_receipts"], 1)
    line("Your monthly income: what you told us vs ITR", "Your answer", profile["personal_monthly_income"] or None,
         "Latest ITR (net profit / 12)", round(metrics["itr_net_annual"] / 12) if metrics["itr_net_annual"] else None, 10)
    line("Monthly EMIs: what you told us vs documents", "Your answer", profile["monthly_emi"],
         "Bank and loan statements", metrics["existing_emi"], 3)
    if bs:
        march = next((m for m in months if m["month"].endswith("-03")), None)
        line("Bank balance at 31 March: statement vs balance sheet", "Bank statement",
             march["closing_balance"] if march else None, "Balance sheet", fields(bs)["bank_balance"], 0)

    # ---- findings
    findings: list[dict[str, Any]] = []

    def finding(fid: str, category: str, title: str, severity: str, state: str, explanation: str,
                figures: dict[str, Any], evidence: list[dict[str, str]], questions: list[str], action: str,
                dimension: str | None) -> None:
        findings.append({"id": fid, "category": category, "title": title, "severity": severity,
                         "verification_state": state, "explanation": explanation, "figures": figures,
                         "evidence": evidence, "source_documents": sorted({e["document_title"] for e in evidence}),
                         "unresolved_questions": questions, "next_action": action, "dimension": dimension})

    bank_refs = [_ref(m_doc, "Business receipts (classified)", m["business_receipts"])
                 for m, m_doc in zip(months, bank_docs)]
    dscr_req = metrics["dscr_with_requested"]
    if months and dscr_req is not None and dscr_req < 1.25:
        finding(
            "repayment_capacity", "Repayment capacity", "The requested loan may be more than current cash flow can carry",
            "high" if dscr_req < 1 else "medium", "evidence_suggests",
            f"Evidence suggests this is a potential contributing factor. Bank statements show about {rs(surplus)} a "
            f"month left after running costs. Existing EMIs take {rs(metrics['existing_emi'])}. A loan of "
            f"{rs(requested)} at an illustrative {ILLUSTRATIVE_RATE:g}% over {ILLUSTRATIVE_TENURE} months would add "
            f"about {rs(new_emi)}, so repayments would be {rs(metrics['existing_emi'] + new_emi)} against "
            f"{rs(surplus)} available (cover of {dscr_req}x).",
            {"avg_operating_surplus": surplus, "existing_emi": metrics["existing_emi"], "illustrative_new_emi": new_emi,
             "dscr_with_requested": dscr_req, "illustrative_rate_pct": ILLUSTRATIVE_RATE,
             "illustrative_tenure_months": ILLUSTRATIVE_TENURE},
            bank_refs[-3:] + [_ref(loan_docs[o["account_no"]], "EMI", o["emi"]) for o in active if o["documented"]],
            ["The rate and tenure are illustrative; each lender applies its own."],
            "Test a smaller amount, a longer tenure or a different product type.", "amount")
    gap = metrics["declared_vs_bank_gap_pct"]
    if months and gap is not None and gap > 15:
        answered = answers.get("revenue-gap")
        finding(
            "revenue_evidence_gap", "Income evidence", "Sales you described are higher than the documents show",
            "high" if gap > 25 else "medium", "requires_confirmation" if not answered else "evidence_suggests",
            f"You told us sales are about {rs(profile['monthly_revenue'])} a month. Business receipts in the bank "
            f"statements average {rs(metrics['avg_business_receipts'])}"
            + (f" and GST returns show {rs(metrics['avg_gst_turnover'])} of taxable turnover" if gst_months else "")
            + ". Lenders generally rely on documented figures, so this gap is a potential contributing factor. "
              "A gap like this is common and does not by itself mean anything was misstated.",
            {"declared_monthly_revenue": profile["monthly_revenue"],
             "avg_business_receipts": metrics["avg_business_receipts"], "avg_gst_turnover": metrics["avg_gst_turnover"],
             "gap_pct": gap},
            bank_refs + [_ref(d, "3.1(a) Outward taxable supplies", fields(d)["taxable"]) for d in gst_docs],
            [] if answered else ["What explains the difference between your estimate and the documents?"],
            "Add evidence for sales that do not pass through this bank account, or plan around the documented figure.",
            "evidence")
    bank_gst = metrics["bank_vs_gst_gap_pct"]
    if bank_gst is not None and abs(bank_gst) > 15:
        finding(
            "gst_bank_mismatch", "Consistency", "Bank receipts and GST returns do not agree",
            "high", "requires_confirmation",
            f"Over the same months, business receipts in the bank are {abs(bank_gst)}% "
            f"{'higher' if bank_gst > 0 else 'lower'} than GST turnover with tax added. This may be a timing or "
            "reporting difference (for example exempt goods or unbilled sales); it requires confirmation and is "
            "not evidence of wrongdoing. A lender that assesses income from GST returns would see the lower figure.",
            {"bank_receipts": sum(m["business_receipts"] for m in gst_months),
             "gst_gross": sum(m["gst_gross"] for m in gst_months), "gap_pct": bank_gst},
            bank_refs[-3:] + [_ref(d, "3.1(a) Outward taxable supplies", fields(d)["taxable"]) for d in gst_docs[-3:]],
            ["Are some sales exempt from GST, or billed outside these returns?"],
            "Reconcile sales registers with GST returns; consider a lender that assesses from banking.", "evidence")
    elif bank_gst is not None and months:
        finding(
            "gst_bank_reconciled", "Consistency", "Bank receipts and GST returns agree over the year", "info",
            "confirmed_in_document",
            f"Business receipts in the bank are within {abs(bank_gst)}% of GST turnover with tax added. "
            "Month-to-month differences look like collection timing.",
            {"gap_pct": bank_gst}, bank_refs[-2:] + [_ref(d, "3.1(a) Outward taxable supplies", fields(d)["taxable"])
                                                      for d in gst_docs[-2:]],
            [], "No action needed. This supports the documented turnover.", None)
    itr_monthly = round(metrics["itr_net_annual"] / 12) if metrics["itr_net_annual"] else None
    if itr_monthly and (profile["personal_monthly_income"] or 0) > itr_monthly * 1.15:
        finding(
            "income_evidence_gap", "Income evidence", "Your stated income is higher than your tax return shows",
            "medium", "confirmed_in_document",
            f"You told us you take home about {rs(profile['personal_monthly_income'])} a month. The latest ITR shows "
            f"net business income of {rs(metrics['itr_net_annual'])} for the year, about {rs(itr_monthly)} a month. "
            "Lenders that assess income from the ITR would use the lower figure.",
            {"declared_personal_income": profile["personal_monthly_income"], "itr_net_annual": metrics["itr_net_annual"],
             "itr_monthly": itr_monthly},
            [_ref(itr, "Net profit from business", fields(itr)["net_income"])], [],
            "Consider lenders that assess from bank cash flow, or an eligible co-applicant.", "structure")
    if metrics["existing_emi"] and surplus > 0 and metrics["existing_emi"] / surplus > 0.5:
        share = calc.ratio(metrics["existing_emi"] / surplus * 100)
        finding(
            "existing_obligations", "Existing commitments", "Existing EMIs already use much of the monthly surplus",
            "high" if share > 75 else "medium", "confirmed_in_document",
            f"{len(active)} running loan(s) cost {rs(metrics['existing_emi'])} a month, {share}% of the "
            f"{rs(surplus)} left after running costs. That leaves {rs(metrics['avg_free_cash'])} for any new EMI.",
            {"existing_emi": metrics["existing_emi"], "avg_operating_surplus": surplus, "share_pct": share,
             "outstanding_total": metrics["outstanding_total"]},
            [_ref(loan_docs[o["account_no"]], "EMI", o["emi"]) for o in active if o["documented"]], [],
            "Look at restructuring or consolidating existing loans before adding a new one.", "liabilities")
    if metrics["emi_returns_12m"]:
        ev = [_ref(d, f"{r['date']} {r['narration']}", r["debit"]) for d, r in bounce_rows]
        if history:
            ev += [_ref(history, f"{r['account_no']} due {r['due_date']}: {r['status']}", r["emi"])
                   for r in history["extraction"]["rows"] if r["days_late"]]
        finding(
            "emi_return", "Repayment track", f"{metrics['emi_returns_12m']} EMI was returned in the last 12 months"
            if metrics["emi_returns_12m"] == 1 else f"{metrics['emi_returns_12m']} EMIs were returned in the last 12 months",
            "medium" if metrics["emi_returns_12m"] <= 1 else "high", "confirmed_in_document",
            "Confirmed in the supplied documents: the bank statement shows a return charge and the repayment "
            "history shows the instalment was paid late. Many lenders limit how many returns they accept.",
            {"emi_returns_12m": metrics["emi_returns_12m"]}, ev,
            ["What caused the return (timing of receipts, a one-off event)?"],
            "Prepare a short explanation and keep the EMI date after your usual collection dates.", "documentation")
    if late_docs:
        finding(
            "late_gst_filings", "Compliance", f"{len(late_docs)} GST return(s) were filed after the due date",
            "low" if len(late_docs) <= 2 else "medium", "confirmed_in_document",
            "Confirmed in the supplied documents. Occasional short delays are common, but some lenders count them.",
            {"late_gst_filings": len(late_docs), "longest_delay_days": max(fields(d)["days_late"] for d in late_docs)},
            [_ref(d, f"Filed {fields(d)['filed']}, due {fields(d)['due']}", f"{fields(d)['days_late']} days late")
             for d in late_docs], [], "File on time from now on; a clean recent run helps.", "documentation")
    if metrics["cash_share_pct"] > 30:
        finding(
            "cash_heavy_receipts", "Income evidence", "A large share of sales arrives as cash deposits",
            "medium" if metrics["cash_share_pct"] > 40 else "low", "evidence_suggests",
            f"{metrics['cash_share_pct']}% of business receipts are cash deposits. Cash sales are genuine income, "
            "but they are harder for a lender to trace to a customer, so some lenders discount them.",
            {"cash_share_pct": metrics["cash_share_pct"], "paytm_share_pct": metrics["paytm_share_pct"]},
            [_ref(d, "Cash deposits (classified)", m["cash_deposits"]) for m, d in zip(months, bank_docs)][-4:], [],
            "Digital collection records (for example Paytm settlements) can support the sales figure.", "evidence")
    credit_total = sum(m["total_credits"] or 0 for m in months)
    if credit_total and metrics["non_business_credit_total"] / credit_total > 0.05:
        finding(
            "non_business_credits", "Cash flow", "Not every credit in the account is sales income", "info",
            "confirmed_in_document",
            f"Total credits average {rs(metrics['avg_total_credits'])} a month, but "
            f"{rs(metrics['non_business_credit_total'])} over the period came from own-account transfers, capital "
            "brought in, refunds or loan proceeds. Sales receipts are therefore lower than total credits.",
            {"avg_total_credits": metrics["avg_total_credits"], "avg_business_receipts": metrics["avg_business_receipts"],
             "non_business_credit_total": metrics["non_business_credit_total"]},
            [_ref(d, "Total credits", m["total_credits"]) for m, d in zip(months, bank_docs)][-3:], [],
            "No action needed. LoanKart uses sales receipts, not total credits, in every calculation.", None)
    if unclassified:
        finding(
            "unidentified_credits", "Cash flow", f"{len(unclassified)} credit(s) could not be identified", "medium",
            "requires_confirmation",
            f"Credits worth {rs(metrics['unclassified_credit_total'])} carry no invoice reference or known pattern. "
            "They are left out of sales until you tell us what they are.",
            {"unclassified_credit_total": metrics["unclassified_credit_total"]},
            [_ref(u["doc"], f"{u['row']['date']} {u['row']['narration']}", u["row"]["credit"]) for u in unclassified],
            ["What was each of these credits?"], "Answer the questions below so they are treated correctly.",
            "documentation")
    for o in undocumented:
        hits = emi_series[next(k for k in emi_series if k[1] == o["account_no"])]
        disb = [(d, r) for d, r in disbursements if o["account_no"] in r["narration"]]
        finding(
            f"undocumented_loan_{o['account_no']}", "Existing commitments",
            f"A loan from {o['lender']} appears in the bank statement without a loan statement",
            "low" if o["status"] == "ended" else "medium", "requires_confirmation",
            (f"A disbursement of {rs(disb[0][1]['credit'])} and " if disb else "")
            + f"{o['months_seen']} repayments of {rs(o['emi'])} are visible, the last in {o['last_seen']}. "
            + ("Evidence suggests it is fully repaid, but that requires confirmation."
               if o["status"] == "ended" else "It appears to be still running."),
            {"emi": o["emi"], "months_seen": o["months_seen"], "last_seen": o["last_seen"]},
            [_ref(d, f"{r['date']} {r['narration']}", r["credit"]) for d, r in disb]
            + [_ref(h[2], f"{h[3]['date']} {h[3]['narration']}", h[1]) for h in hits],
            ["Is this loan closed? A closure letter would settle it."],
            "Add the loan statement or closure letter.", "documentation")
    if vintage is not None and vintage < 3:
        finding(
            "business_vintage", "Eligibility", f"The business is {vintage} years old", "high" if vintage < 1 else "medium",
            "confirmed_in_document",
            "Confirmed in the supplied registration certificate. Many lenders set a minimum age for the business; "
            "this is a potential contributing factor where that minimum is higher.",
            {"vintage_years": vintage, "declared_vintage_years": profile["business_vintage_years"]},
            [_ref(udyam, "Date of commencement of business", fields(udyam)["commenced"])], [],
            "Look at products designed for newer businesses, or a co-applicant with an established income.", "product")
    if missing:
        finding(
            "documentation_gaps", "Documentation", f"{len(missing)} document(s) lenders usually ask for are missing",
            "high" if len(missing) >= 3 else "medium", "confirmed_in_document",
            "Missing: " + "; ".join(m["label"] for m in missing) + ". Without them several lenders cannot assess the case.",
            {"missing_count": len(missing)}, [], [], "See which documents can be prepared and add them.",
            "documentation")
    if months and requested > 4 * metrics["avg_business_receipts"]:
        multiple = calc.ratio(requested / max(metrics["avg_business_receipts"], 1))
        finding(
            "amount_vs_turnover", "Loan size", "The amount is large compared with monthly sales", "medium",
            "evidence_suggests",
            f"The amount requested is {multiple} times average monthly sales receipts. Unsecured products often cap "
            "the amount at a multiple of sales, so this is a potential contributing factor for unsecured routes.",
            {"requested_amount": requested, "avg_business_receipts": metrics["avg_business_receipts"],
             "multiple": multiple}, bank_refs[-3:], [],
            "Compare secured products, which size the loan on the security instead.", "collateral")
    trend = metrics["revenue_trend_pct"]
    if trend is not None and trend < -15:
        finding(
            "revenue_decline", "Cash flow", "Recent receipts are lower than earlier in the year", "medium",
            "evidence_suggests", f"The last three months average {abs(trend)}% below the first three. This may be "
            "seasonal; it requires confirmation.", {"revenue_trend_pct": trend}, bank_refs[:3] + bank_refs[-3:],
            ["Is this a seasonal pattern?"], "Be ready to explain the seasonality.", "evidence")
    if rejection:
        rf = fields(rejection)
        finding(
            "stated_rejection_reason", "Previous rejection", "What the lender's letter says", "info",
            "confirmed_in_document",
            f"Confirmed in the supplied document: {rejection['extraction']['issuer']} declined a {rf['product']} of "
            f"{rs(rf['amount'])} on {rf['date']}, stating: \"{rf['reason']}\" The letter does not give the lender's "
            "detailed assessment; the other findings are possible contributing factors, not the lender's confirmed reasons.",
            {"amount": rf["amount"], "date": rf["date"]}, [_ref(rejection, "Reason communicated", rf["reason"])], [],
            "Use the findings below to see what may sit behind this reason.", None)
    if valuation:
        finding(
            "collateral_available", "Security", "Security is available if you choose to offer it", "info",
            "confirmed_in_document",
            f"The valuation report puts {fields(valuation)['description']} at {rs(collateral_value)}. Offering "
            "security can widen the options, and puts that asset at risk if repayments are missed.",
            {"collateral_value": collateral_value}, [_ref(valuation, "Assessed market value", collateral_value)], [],
            "Compare secured and unsecured routes before deciding.", "collateral")
    order = {"high": 0, "medium": 1, "low": 2, "info": 3}
    findings.sort(key=lambda f: order[f["severity"]])

    # ---- clarifications the borrower can answer
    clarifications = [{
        "id": u["id"], "question": f"What was the credit of {rs(u['row']['credit'])} on {u['row']['date']} "
                                   f"(\"{u['row']['narration']}\")?",
        "why": "It has no invoice reference, so it is counted as sales only if you say it was.",
        "options": [{"code": k, "label": v} for k, v in CREDIT_ANSWERS.items()],
        "answer": answers.get(u["id"]), "finding_id": "unidentified_credits"} for u in asked]
    if gap is not None and gap > 15 and months:
        clarifications.append({
            "id": "revenue-gap",
            "question": f"You estimated sales of {rs(profile['monthly_revenue'])} a month; documents show about "
                        f"{rs(metrics['avg_business_receipts'])}. What best explains the difference?",
            "why": "Lenders rely on documented figures. Knowing the reason tells us which evidence could help.",
            "options": [{"code": "undeposited_cash", "label": "Some cash sales never reach this bank account"},
                        {"code": "other_account", "label": "Some sales go to another account"},
                        {"code": "estimate_high", "label": "My estimate was on the high side"},
                        {"code": "not_sure", "label": "I'm not sure"}],
            "answer": answers.get("revenue-gap"), "finding_id": "revenue_evidence_gap"})

    state = lambda key, default: ("corrected" if key in originals else default)  # noqa: E731
    headline = [
        {"key": "avg_business_receipts", "label": "Average monthly sales receipts", "value": metrics["avg_business_receipts"],
         "unit": "inr", "state": state("avg_business_receipts", "extracted"), "source": f"{len(months)} bank statements"},
        {"key": "avg_total_credits", "label": "Average monthly total credits", "value": metrics["avg_total_credits"],
         "unit": "inr", "state": "verified", "source": "Bank statement totals"},
        {"key": "avg_gst_turnover", "label": "Average monthly GST turnover", "value": metrics["avg_gst_turnover"],
         "unit": "inr", "state": "verified" if gst_months else "missing", "source": f"{len(gst_docs)} GSTR-3B returns"},
        {"key": "declared_monthly_revenue", "label": "Monthly sales you told us", "value": profile["monthly_revenue"],
         "unit": "inr", "state": "declared", "source": "Your onboarding answer"},
        {"key": "avg_operating_expenses", "label": "Average monthly running costs", "value": metrics["avg_operating_expenses"],
         "unit": "inr", "state": state("avg_operating_expenses", "extracted"), "source": "Bank statement debits (classified)"},
        {"key": "avg_operating_surplus", "label": "Left after running costs", "value": surplus, "unit": "inr",
         "state": "calculated", "source": "Sales receipts minus running costs"},
        {"key": "existing_emi", "label": "Existing EMIs", "value": metrics["existing_emi"], "unit": "inr",
         "state": state("existing_emi", "verified" if active and all(o["documented"] for o in active) else "extracted"),
         "source": "Loan statements and bank debits"},
        {"key": "avg_free_cash", "label": "Free cash after EMIs", "value": metrics["avg_free_cash"], "unit": "inr",
         "state": "calculated", "source": "Surplus minus existing EMIs"},
        {"key": "itr_net_annual", "label": "Net income in latest ITR (year)", "value": metrics["itr_net_annual"],
         "unit": "inr", "state": "verified" if itr else "missing", "source": "ITR acknowledgement"},
        {"key": "emi_returns_12m", "label": "EMI returns in 12 months", "value": metrics["emi_returns_12m"],
         "unit": "count", "state": state("emi_returns_12m", "verified"), "source": "Bank statement and repayment history"},
        {"key": "collateral_value", "label": "Security value", "value": metrics["collateral_value"], "unit": "inr",
         "state": state("collateral_value", "verified" if valuation else "missing"), "source": "Valuation report"},
    ]
    for h in headline:
        if h["key"] in originals:
            h["original"], h["corrected_by"] = originals[h["key"]], corrections[h["key"]].get("by", "advisor")

    return {
        "months": months, "classification": {"counts": dict(counts), "unclassified": len(unclassified)},
        "obligations": obligations, "metrics": metrics, "headline": headline, "reconciliation": recon,
        "findings": findings, "clarifications": clarifications, "missing_documents": missing, "unusual": unusual,
        "document_types": {t: len(ds) for t, ds in by_type.items()}, "corrected_from": originals,
    }


def build_facts(result: dict[str, Any], profile: dict[str, Any]) -> dict[str, Any]:
    """The borrower's position as a lender would be shown it: documented figures only, no declared estimates."""
    m = result["metrics"]
    value = m["collateral_value"] or profile.get("collateral_value")   # valuation report, else what was declared
    return {
        "requested_amount": profile["requested_amount"], "tenure_months": ILLUSTRATIVE_TENURE,
        "vintage_years": m["vintage_years"], "gst_registered": bool(result["document_types"].get("gstr3b")),
        "monthly_revenue": m["avg_business_receipts"], "gst_monthly_turnover": m["avg_gst_turnover"],
        "operating_surplus": m["avg_operating_surplus"],
        "itr_monthly_income": round(m["itr_net_annual"] / 12) if m["itr_net_annual"] else None,
        "existing_emi": m["existing_emi"], "active_loans": m["active_loans"],
        "emi_returns_12m": m["emi_returns_12m"], "late_gst_filings": m["late_gst_filings"],
        "cash_share_pct": m["cash_share_pct"],
        "collateral": {"type": profile["collateral"], "value": value} if profile["collateral"] != "none" else None,
        "collateral_offered": profile["collateral"] != "none", "purpose": profile["loan_purpose"],
        "takeover": {"amount": 0, "emi": 0, "count": 0},
        "documents": sorted(set(result["document_types"]) - ({"itr"} if m["itr_years"] < 2 else set())),
        "open_clarifications": sum(1 for c in result["clarifications"] if not c["answer"] or c["answer"] == "not_sure"),
        "co_applicant_income": 0, "supplementary_evidence": [],
    }
