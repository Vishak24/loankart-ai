"""Baseline document extraction (input to Layer C).

Reads a PDF's text and turns it into structured fields and rows. It knows document layouts, not answers: it never
touches the ground-truth dataset. `parse_text` works on plain text, so a different text source (for example
Sarvam Vision OCR for scanned documents) can feed the same parser.
"""

import re
from pathlib import Path
from typing import Any

import pdfplumber

AMT = r"-?[\d,]+\.\d{2}"
DATE = r"\d{2}-\d{2}-\d{4}"

DOC_TYPES = [
    ("STATEMENT OF ACCOUNT", "bank_statement"), ("FORM GSTR-3B", "gstr3b"), ("FORM GSTR-1", "gstr1"),
    ("INCOME TAX RETURN ACKNOWLEDGEMENT", "itr"), ("LOAN ACCOUNT STATEMENT", "loan_statement"),
    ("EMI REPAYMENT TRACK", "repayment_history"), ("PROFIT AND LOSS ACCOUNT", "pnl"),
    ("BALANCE SHEET", "balance_sheet"), ("CASH FLOW STATEMENT", "cash_flow"),
    ("LOAN APPLICATION DECISION", "rejection_letter"), ("UDYAM REGISTRATION CERTIFICATE", "udyam_certificate"),
    ("FORM GST REG-06", "gst_certificate"), ("VALUATION REPORT", "collateral_valuation"),
]

# field key -> (label printed in the document, kind)
FIELDS: dict[str, dict[str, tuple[str, str]]] = {
    "bank_statement": {
        "account_holder": ("Account holder", "text"), "account_number": ("Account number", "text"),
        "month": ("Statement month", "text"), "opening_balance": ("Opening balance", "amount"),
        "total_credits": ("Total credits", "amount"), "total_debits": ("Total debits", "amount"),
        "closing_balance": ("Closing balance", "amount")},
    "gstr3b": {
        "gstin": ("GSTIN", "text"), "month": ("Return month", "text"),
        "taxable": ("3.1(a) Outward taxable supplies", "amount"), "tax": ("Total tax liability", "amount"),
        "itc": ("Input tax credit availed", "amount"), "net_cash": ("Tax paid in cash", "amount"),
        "due": ("Due date", "date"), "filed": ("Date of filing", "date"), "days_late": ("Days late", "int"),
        "late_fee": ("Late fee", "amount")},
    "gstr1": {
        "gstin": ("GSTIN", "text"), "month": ("Return month", "text"), "b2b_value": ("B2B taxable value", "amount"),
        "b2c_value": ("B2C taxable value", "amount"), "taxable": ("Total taxable value", "amount"),
        "tax": ("Total tax", "amount"), "filed": ("Date of filing", "date")},
    "itr": {
        "name": ("Name", "text"), "ay": ("Assessment year", "text"),
        "gross_receipts": ("Gross receipts from business", "amount"),
        "net_income": ("Net profit from business", "amount"), "filed": ("Date of filing", "date")},
    "loan_statement": {
        "account_no": ("Loan account number", "text"), "product": ("Product", "text"), "security": ("Security", "text"),
        "principal": ("Sanctioned amount", "amount"), "rate": ("Rate of interest", "rate"),
        "tenure": ("Tenure", "int"), "emi": ("EMI", "amount"), "disbursed": ("Date of disbursal", "date"),
        "remaining": ("Instalments remaining", "int"), "outstanding": ("Principal outstanding", "amount"),
        "overdue": ("Overdue amount", "amount")},
    "repayment_history": {
        "due_count": ("Instalments due in period", "int"), "on_time": ("Paid on due date", "int"),
        "late": ("Returned or paid late", "int")},
    "pnl": {
        "revenue": ("Revenue from operations", "amount"), "cost_of_goods_sold": ("Cost of goods sold", "amount"),
        "gross_profit": ("Gross profit", "amount"), "interest": ("Interest on loans", "amount"),
        "depreciation": ("Depreciation", "amount"), "net_profit": ("Net profit before tax", "amount")},
    "balance_sheet": {
        "capital": ("Proprietor's capital", "amount"), "secured_loans": ("Secured loans", "amount"),
        "unsecured_loans": ("Unsecured loans", "amount"), "creditors": ("Sundry creditors", "amount"),
        "stock": ("Stock in trade", "amount"), "debtors": ("Sundry debtors", "amount"),
        "bank_balance": ("Bank balance", "amount"), "total_assets": ("Total assets", "amount")},
    "cash_flow": {
        "cash_from_operations": ("Net cash from operating activities", "amount"),
        "loan_principal_repaid": ("Loan principal repaid", "amount"),
        "owner_drawings": ("Proprietor's drawings", "amount"), "closing_cash": ("Closing cash and bank", "amount")},
    "rejection_letter": {
        "date": ("Date", "date"), "reference": ("Reference", "text"), "product": ("Product applied for", "text"),
        "amount": ("Amount applied for", "amount")},
    "udyam_certificate": {
        "udyam_no": ("Udyam registration number", "text"),
        "commenced": ("Date of commencement of business", "date"), "activity": ("Major activity", "text")},
    "gst_certificate": {"gstin": ("GSTIN", "text"), "registered_on": ("Date of registration", "date")},
    "collateral_valuation": {
        "asset_type": ("Asset type", "text"), "description": ("Description", "text"),
        "value": ("Assessed market value", "amount"), "valued_on": ("Date of valuation", "date")},
}


def amount(text: str) -> int:
    return round(float(text.replace(",", "")))


def iso(dmy: str) -> str:
    d, m, y = dmy.split("-")
    return f"{y}-{m}-{d}"


def _convert(raw: str, kind: str) -> Any:
    if kind == "amount":
        return amount(raw) if re.fullmatch(AMT, raw) else None
    if kind == "date":
        return iso(raw) if re.fullmatch(DATE, raw) else None
    if kind in ("int", "rate"):
        m = re.match(r"[\d.]+", raw)
        return None if not m else (float(m.group()) if kind == "rate" else int(float(m.group())))
    return raw


def read_text(path: Path) -> list[str]:
    with pdfplumber.open(path) as pdf:
        lines = [line.strip() for page in pdf.pages for line in (page.extract_text() or "").split("\n")]
    return [ln for ln in lines if ln and not ln.startswith(("SYNTHETIC DEMO DOCUMENT", "Generated by the LoanKart.ai"))]


def parse_text(lines: list[str]) -> dict[str, Any]:
    """Structured extraction from document text. Unknown layouts return doc_type None."""
    head = " ".join(lines[:4])
    doc_type = next((t for marker, t in DOC_TYPES if marker in head), None)
    out: dict[str, Any] = {"doc_type": doc_type, "issuer": lines[0] if lines else None, "fields": {}, "rows": [],
                           "checks": [], "warnings": []}
    if doc_type is None:
        out["warnings"].append("Layout not recognised by the baseline parser.")
        return out

    for key, (label, kind) in FIELDS[doc_type].items():
        line = next((ln for ln in lines if ln.startswith(label + " ")), None)
        value = _convert(line[len(label) + 1:].strip(), kind) if line else None
        out["fields"][key] = value
        if value is None:
            out["warnings"].append(f"'{label}' was not found.")

    f = out["fields"]
    if doc_type == "bank_statement":
        row_re = re.compile(rf"^({DATE}) (.+) (\d{{10}}) ({AMT}) ({AMT})$")
        balance = f["opening_balance"] or 0
        for ln in lines:
            m = row_re.match(ln)
            if not m:
                continue
            value, new_balance = amount(m.group(4)), amount(m.group(5))
            credit = new_balance >= balance          # the layout leaves the unused column blank; the balance tells
            if abs(new_balance - balance) != value:
                out["warnings"].append(f"Balance does not follow from the amount on {m.group(1)} ref {m.group(3)}.")
            out["rows"].append({"date": iso(m.group(1)), "narration": m.group(2), "ref": m.group(3),
                                "debit": 0 if credit else value, "credit": value if credit else 0,
                                "balance": new_balance})
            balance = new_balance
        credits, debits = sum(r["credit"] for r in out["rows"]), sum(r["debit"] for r in out["rows"])
        out["checks"] = [
            {"name": "Running balance ends at the stated closing balance", "ok": balance == f["closing_balance"]},
            {"name": "Credits add up to the stated total", "ok": credits == f["total_credits"]},
            {"name": "Debits add up to the stated total", "ok": debits == f["total_debits"]}]
    elif doc_type == "loan_statement":
        row_re = re.compile(rf"^(\d+) ({DATE}) ({AMT}) ({AMT}) ({AMT}) ({AMT}) (.+)$")
        for m in filter(None, map(row_re.match, lines)):
            out["rows"].append({"no": int(m.group(1)), "due_date": iso(m.group(2)), "emi": amount(m.group(3)),
                                "principal": amount(m.group(4)), "interest": amount(m.group(5)),
                                "balance": amount(m.group(6)), "status": m.group(7)})
        if out["rows"]:
            out["checks"] = [{"name": "Last instalment balance equals the stated outstanding principal",
                              "ok": out["rows"][-1]["balance"] == f["outstanding"]}]
    elif doc_type == "repayment_history":
        row_re = re.compile(rf"^(\S+) ({DATE}) ({AMT}) ({DATE}) (\d+) (.+)$")
        for m in filter(None, map(row_re.match, lines)):
            out["rows"].append({"account_no": m.group(1), "due_date": iso(m.group(2)), "emi": amount(m.group(3)),
                                "paid_date": iso(m.group(4)), "days_late": int(m.group(5)), "status": m.group(6)})
    elif doc_type == "rejection_letter":
        m = re.search(r"Reason communicated: (.+?) This letter", " ".join(lines))
        f["reason"] = m.group(1) if m else None
    return out


def extract_document(path: Path) -> dict[str, Any]:
    try:
        return parse_text(read_text(path))
    except Exception as exc:  # unreadable or corrupt file: report it, never crash the investigation
        return {"doc_type": None, "issuer": None, "fields": {}, "rows": [], "checks": [],
                "warnings": [f"Could not read this file: {exc.__class__.__name__}."]}


# ---------------------------------------------------------------------------------------------- uploaded files

MAX_PDF_PAGES = 25
WORKER_TIMEOUT_S = 20
# Active content a financial document never needs. A heuristic on the raw bytes: names can be obfuscated, which is why
# the file is also parsed in an isolated process and served without being executed server-side. No bare "/JS": a JavaScript
# action always carries "/S /JavaScript", and "/JS" alone matched ~15% of random 5 MB compressed streams (scanned statements).
_ACTIVE = re.compile(rb"/(?:JavaScript|Launch|EmbeddedFile|RichMedia|SubmitForm|ImportData|Encrypt)(?![A-Za-z0-9])")


def validate_pdf_bytes(content: bytes) -> None:
    """Cheap structural checks before anything is written or parsed. Raises ValueError with a message for the user."""
    if not content.startswith(b"%PDF-") or b"%%EOF" not in content[-2048:]:
        raise ValueError("Only complete PDF files are accepted.")
    if _ACTIVE.search(content):
        raise ValueError("This PDF contains scripts, attachments or encryption, which are not accepted.")


def extract_upload(path: Path) -> dict[str, Any]:
    """extract_document for files from outside: same result, run in an isolated process with a time limit.
    Raises ValueError for a PDF that breaks the limits (too many pages, too slow, damaged, locked)."""
    import json
    import os
    import subprocess
    import sys

    worker = Path(__file__).with_name("extraction_worker.py")
    try:
        done = subprocess.run([sys.executable, "-I", str(worker), str(path), str(MAX_PDF_PAGES)], capture_output=True,
                              timeout=WORKER_TIMEOUT_S, env={"PATH": os.environ.get("PATH", "")}, check=False)
    except subprocess.TimeoutExpired:
        raise ValueError("The PDF took too long to read and was rejected.") from None
    try:
        result = json.loads(done.stdout[:5_000_000] or b"null")
    except ValueError:
        result = None
    if not isinstance(result, dict):
        raise ValueError("The PDF could not be read safely and was rejected.")
    if "error" in result:
        raise ValueError(str(result["error"]))
    return result
