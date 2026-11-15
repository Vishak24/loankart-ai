"""Layer B: ground-truth synthetic datasets.

Every person, business, lender, account number and figure here is invented. A scenario is a small set of explicit
parameters (including the deliberate discrepancies); `build_dataset` expands it deterministically (seeded RNG, no
clock, no uuid) into transactions, returns, loan schedules and statements. The PDF factory renders documents from
this dataset. The investigation code (extraction.py, analysis.py) must never import this module: it only sees the
PDFs. Tests compare its findings against `dataset["truth"]`.
"""

import calendar
import random
import zlib
from copy import deepcopy
from typing import Any

from . import calculations as calc

MONTHS = ["2025-11", "2025-12", "2026-01", "2026-02", "2026-03", "2026-04",
          "2026-05", "2026-06", "2026-07", "2026-08", "2026-09", "2026-10"]
AS_OF = "2026-10-31"
FY_LABEL, FY_START, FY_END, FY_AY = "2025-26", "2025-04", "2026-03", "2026-27"
PRIMARY_SCENARIO = "tiruppur_textile"
SEASON = [1.08, 0.97, 0.94, 0.90, 1.02, 0.95, 0.88, 0.90, 0.95, 1.00, 1.06, 1.35]  # festival peak in Oct-Nov

BUYERS = ["SRI MURUGAN GARMENTS", "ANNAI TEXTILES", "VELAN READYMADES", "KAVIN FASHIONS", "THIRUMALAI STORES",
          "PONNI DRESS MART", "ARASI SILKS", "MALAR GARMENTS", "SENTHIL TRADERS", "NILA BOUTIQUE"]
SUPPLIERS = ["ESWARI KNITS", "SAKTHI YARN MILLS", "VETRIVEL PROCESSORS", "AMUDHA DYEING", "KANNAN PACKAGING"]
GENERIC_BUYERS = ["ARUN ENTERPRISES", "BHARATHI AGENCIES", "CHOLA INDUSTRIES", "DEEPAM STORES", "EZHIL TRADERS",
                  "GANGA ASSOCIATES", "INBA MARKETING", "JOTHI & CO"]
GENERIC_SUPPLIERS = ["SRI BALAJI TRADERS", "MUTHU SUPPLIES", "PANDIAN WHOLESALE", "RAJAM DISTRIBUTORS",
                     "TAMIL INDUSTRIAL STORES"]


def month_add(ym: str, k: int) -> str:
    y, m = map(int, ym.split("-"))
    total = y * 12 + (m - 1) + k
    return f"{total // 12:04d}-{total % 12 + 1:02d}"


def _date(ym: str, day: int) -> str:
    y, m = map(int, ym.split("-"))
    return f"{ym}-{min(day, calendar.monthrange(y, m)[1]):02d}"


def _split(total: int, n: int, rng: random.Random, step: int = 100) -> list[int]:
    """Up to n positive amounts that sum exactly to total."""
    n = max(1, min(n, total // step))
    weights = [rng.uniform(0.6, 1.4) for _ in range(n)]
    parts = [max(step, int(total * w / sum(weights)) // step * step) for w in weights]
    parts[-1] += total - sum(parts)
    if parts[-1] <= 0:
        raise ValueError(f"cannot split {total} into {n} parts")
    return parts


# --------------------------------------------------------------------------------------------- scenarios

def _profile(**kw: Any) -> dict[str, Any]:
    base = {"state": "Tamil Nadu", "loan_purpose": "working_capital", "gst_status": "registered",
            "business_registration": "udyam_proprietorship", "previously_rejected": False,
            "rejection_reason": None, "rejection_note": None, "collateral": "none", "collateral_value": None,
            "existing_loan_count": 0, "outstanding_loan_amount": 0, "monthly_emi": 0}
    return {**base, **kw}


def _loan(key: str, lender: str, short: str, kind: str, principal: int, rate: float, tenure: int,
          first_emi: str, emi_day: int = 5, secured: bool = False) -> dict[str, Any]:
    return {"key": key, "lender": f"{lender} (fictional)", "short": short, "type": kind, "principal": principal,
            "rate": rate, "tenure": tenure, "first_emi": first_emi, "emi_day": emi_day, "secured": secured,
            "account_no": f"{short.split()[0][:3]}{zlib.crc32(key.encode()) % 10**8:08d}"}


def _receipts(base: int, pattern: list[float] = SEASON) -> list[int]:
    return [round(base * f / 1000) * 1000 for f in pattern]


_TIRUPPUR = {
    "id": PRIMARY_SCENARIO,
    "title": "Tiruppur textile wholesaler (primary demo)",
    "tests": "Declared revenue above bank and GST evidence, existing EMIs, one EMI return, two late GST filings, "
             "a previous rejection.",
    "profile": _profile(
        borrower_name="Karthik Ramesh", business_name="KR Fabrics & Readymades", industry="wholesale_distribution",
        city="Tiruppur", business_vintage_years=4.5, requested_amount=1_500_000,
        monthly_revenue=650_000,           # deliberate: self-reported, above bank and GST evidence
        monthly_expenses=520_000,
        personal_monthly_income=85_000,    # deliberate: above ITR net income (about 60,000 a month)
        collateral="gold", collateral_value=1_120_000, previously_rejected=True,
        rejection_reason="insufficient_income_proof",
        rejection_note="Told the income in my documents did not support the amount I asked for."),
    "entity": {"pan": "AAAPK0000X", "gstin": "33AAAPK0000X1Z0", "udyam_no": "UDYAM-TN-00-0000451",
               "commenced": "2022-05-10", "gst_registered_on": "2022-06-01", "activity": "Wholesale of textiles",
               "address": "14 Kumaran Road, Tiruppur 641601, Tamil Nadu", "paytm_mid": "KRFAB00451"},
    "bank": {"name": "Noyyal Valley Bank (fictional)", "branch": "Tiruppur Main", "account_no": "501000427781",
             "ifsc": "NVBX0000042", "opening_balance": 85_000},
    # Business receipts by month. Annual total 51,66,000 = GST taxable turnover 49,20,000 + 5% GST: the bank and
    # GST evidence reconcile over the year; month-to-month gaps are collection timing.
    "receipts": [478_000, 432_000, 404_000, 385_000, 440_000, 410_000,
                 366_000, 362_000, 390_000, 412_000, 455_000, 632_000],
    "cash_share": 0.36, "paytm_share": 0.12,
    "gst": {"turnover": [470_000, 390_000, 380_000, 360_000, 440_000, 370_000,
                         340_000, 350_000, 380_000, 400_000, 450_000, 590_000],   # average 4.1 lakh
            "rate": 5, "late": {3: 8, 7: 6}},                                      # Feb and Jun 2026 returns
    "opex": {"rent": 18_000, "salaries": [("S MANI", 24_000), ("R DEVI", 20_000), ("K BALU", 18_000)],
             "utilities": 6_000, "transport": 9_000, "variable_ratio": 0.60},
    "drawings": 45_000,
    # Non-business credits, 7,14,000 in total: with them, total credits average 4.9 lakh a month.
    "other_credits": [
        (0, 12, "internal_transfer", "TRF FROM OWN SB A/C XX8890", 60_000),
        (1, 9, "owner_contribution", "CAPITAL INTRODUCED-PROPRIETOR", 50_000),
        (2, 14, "internal_transfer", "TRF FROM OWN SB A/C XX8890", 45_000),
        (4, 22, "refund", "REFUND-ESWARI KNITS-GOODS RETURNED", 18_000),
        (5, 11, "internal_transfer", "TRF FROM OWN SB A/C XX8890", 50_000),
        (6, 16, "owner_contribution", "IMPS CR-P SELVI", 50_000),                 # deliberate: ambiguous narration
        (7, 8, "owner_contribution", "CAPITAL INTRODUCED-PROPRIETOR", 50_000),
        (8, 13, "internal_transfer", "TRF FROM OWN SB A/C XX8890", 40_000),
        (9, 19, "refund", "REFUND-SAKTHI YARN MILLS-EXCESS PAID", 12_000),
        (10, 10, "internal_transfer", "TRF FROM OWN SB A/C XX8890", 55_000),
        (11, 6, "other_credit", "IT REFUND AY 2026-27", 14_000),
        (11, 21, "owner_contribution", "NEFT CR-R KUMARESAN", 120_000),           # deliberate: ambiguous narration
    ],
    "other_debits": [(m, 24, "internal_transfer", "TRF TO OWN SB A/C XX8890", 50_000) for m in (0, 2, 4, 9, 11)],
    "loans": [
        _loan("bl", "Neithal Fincorp", "NEITHAL FIN", "Unsecured business loan", 750_000, 21, 36, "2025-09", 5),
        _loan("cv", "Kurinji Asset Finance", "KURINJI AF", "Commercial vehicle loan", 650_000, 11.5, 36,
              "2025-11", 10, secured=True),
        # Short-term loan taken and repaid inside the statement window. No statement supplied for it.
        _loan("st", "Marutham Business Credit", "MARUTHAM BC", "Short-term business loan", 150_000, 24, 3,
              "2026-03", 15),
    ],
    "bounces": [(6, "bl")],                                                        # May 2026
    "itr": [{"ay": "2025-26", "gross_receipts": 4_150_000, "net_income": 610_000},
            {"ay": "2026-27", "gross_receipts": 4_780_000, "net_income": 720_000}],
    "financials": {"depreciation": 42_000, "other_expenses": 61_000, "fixed_assets": 1_150_000, "stock": 820_000,
                   "debtors": 540_000, "creditors": 465_000, "cash_in_hand": 35_000,
                   "capex": 710_000,              # includes the vehicle bought on the Kurinji loan
                   "opening_cash": 148_000},
    "rejection": {"date": "2026-09-18", "lender": "Kongunadu Traders Bank (fictional)",
                  "product": "Working capital term loan", "amount": 1_500_000, "ref": "KTB/WC/2026/004417",
                  "reason": "Income shown in the submitted documents did not support the requested amount."},
    "collateral": {"type": "gold", "description": "Gold ornaments, 140 g, 22 carat", "value": 1_120_000},
    "missing_documents": [], "buyers": BUYERS, "suppliers": SUPPLIERS,
}


def _make(sid: str, title: str, tests: str, profile: dict[str, Any], base_receipts: int, n: int, **over: Any
          ) -> dict[str, Any]:
    """Compact definition for the secondary scenarios. Everything not overridden is unremarkable on purpose."""
    receipts = over.pop("receipts", None) or _receipts(base_receipts)
    initials = "".join(w[0] for w in profile["business_name"].split()[:2]).upper()
    commenced = month_add("2026-11", -round(profile["business_vintage_years"] * 12))
    scenario = {
        "id": sid, "title": title, "tests": tests, "profile": profile,
        "entity": {"pan": f"AAAP{initials[0]}000{n}X", "gstin": f"33AAAP{initials[0]}000{n}X1Z{n}",
                   "udyam_no": f"UDYAM-TN-00-000{n}612", "commenced": f"{commenced}-01",
                   "gst_registered_on": f"{month_add(commenced, 1)}-01",
                   "activity": title.split(" (")[0], "address": f"{20 + n} Main Road, {profile['city']}, Tamil Nadu",
                   "paytm_mid": f"{initials}MER00{n}"},
        "bank": {"name": "Thamirabarani Small Finance Bank (fictional)", "branch": profile["city"],
                 "account_no": f"60200031{n}{n}04", "ifsc": "TSFX0000017", "opening_balance": 140_000},
        "receipts": receipts, "cash_share": 0.2, "paytm_share": 0.15,
        "gst": {"turnover": [round(r / 1.05 / 1000) * 1000 for r in receipts], "rate": 5, "late": {}},
        "opex": {"rent": 20_000, "salaries": [("STAFF A", 22_000), ("STAFF B", 18_000)], "utilities": 7_000,
                 "transport": 8_000, "variable_ratio": 0.62},
        "drawings": 50_000, "other_credits": [], "other_debits": [], "loans": [], "bounces": [],
        "itr": [{"ay": "2025-26", "gross_receipts": round(base_receipts * 10.2 / 1000) * 1000,
                 "net_income": round(base_receipts * 1.45 / 1000) * 1000},
                {"ay": "2026-27", "gross_receipts": round(base_receipts * 11.3 / 1000) * 1000,
                 "net_income": round(base_receipts * 1.7 / 1000) * 1000}],
        "financials": {"depreciation": 50_000, "other_expenses": 70_000, "fixed_assets": 900_000,
                       "stock": base_receipts * 2, "debtors": base_receipts, "creditors": base_receipts,
                       "cash_in_hand": 40_000, "capex": 80_000, "opening_cash": 160_000},
        "rejection": None, "collateral": None, "missing_documents": [],
        "buyers": GENERIC_BUYERS, "suppliers": GENERIC_SUPPLIERS,
    }
    for key, value in over.items():
        both_dicts = isinstance(scenario.get(key), dict) and isinstance(value, dict)
        scenario[key] = {**scenario[key], **value} if both_dicts else value
    return scenario


SCENARIOS: dict[str, dict[str, Any]] = {s["id"]: s for s in [
    _TIRUPPUR,
    _make("high_emi", "CNC job-work unit with heavy EMIs",
          "Consistent revenue evidence, but four running loans leave little room for a new EMI.",
          _profile(borrower_name="Lakshmi Narayanan", business_name="Sri Lakshmi Engineering Works",
                   industry="manufacturing", city="Coimbatore", business_vintage_years=7.4,
                   requested_amount=2_000_000, loan_purpose="machinery_equipment", monthly_revenue=900_000,
                   monthly_expenses=680_000, personal_monthly_income=110_000, collateral="machinery",
                   collateral_value=1_800_000, previously_rejected=True, rejection_reason="existing_obligations",
                   rejection_note="The officer said my existing EMIs were already too high."),
          900_000, 2,
          opex={"variable_ratio": 0.68, "rent": 30_000}, drawings=90_000, cash_share=0.05, paytm_share=0.03,
          loans=[_loan("m1", "Kurinji Asset Finance", "KURINJI AF", "Machinery loan", 2_400_000, 13.5, 60,
                       "2024-06", 5, True),
                 _loan("m2", "Vaigai Capital Finance", "VAIGAI CAP", "Unsecured business loan", 1_200_000, 19, 36,
                       "2025-04", 7),
                 _loan("m3", "Neithal Fincorp", "NEITHAL FIN", "Unsecured business loan", 800_000, 22, 30,
                       "2025-08", 12),
                 _loan("m4", "Marutham Business Credit", "MARUTHAM BC", "Equipment loan", 600_000, 16, 36,
                       "2026-02", 15, True)],
          rejection={"date": "2026-10-06", "lender": "Noyyal Valley Bank (fictional)",
                     "product": "Business term loan", "amount": 2_000_000, "ref": "NVB/TL/2026/001902",
                     "reason": "Existing repayment obligations are high relative to assessed income."},
          collateral={"type": "machinery", "description": "2 CNC turning centres (2023)", "value": 1_800_000},
          financials={"fixed_assets": 4_500_000}),
    _make("gst_mismatch", "Provision store with GST and bank mismatch",
          "Bank receipts are far above GST-declared turnover: an unexplained reporting gap, not proof of wrongdoing.",
          _profile(borrower_name="Annamalai Subbu", business_name="Annam Provision Stores",
                   industry="retail_trading", city="Madurai", business_vintage_years=9.0,
                   requested_amount=1_000_000, loan_purpose="inventory", monthly_revenue=720_000,
                   monthly_expenses=610_000, personal_monthly_income=70_000),
          720_000, 3,
          gst={"turnover": [round(r * 0.61 / 1000) * 1000 for r in _receipts(720_000)]},   # deliberate gap
          opex={"variable_ratio": 0.74}, cash_share=0.45, paytm_share=0.25,
          itr=[{"ay": "2025-26", "gross_receipts": 5_100_000, "net_income": 540_000},
               {"ay": "2026-27", "gross_receipts": 5_350_000, "net_income": 590_000}]),
    _make("low_vintage", "Ten-month-old cloud kitchen",
          "Healthy, growing cash flow but the business is too new for most lenders.",
          _profile(borrower_name="Thendral Raj", business_name="Thendral Cloud Kitchen",
                   industry="food_hospitality", city="Chennai", business_vintage_years=0.8,
                   requested_amount=500_000, loan_purpose="business_expansion", monthly_revenue=330_000,
                   monthly_expenses=250_000, personal_monthly_income=45_000),
          300_000, 4,
          receipts=[0, 0, 150_000, 210_000, 260_000, 290_000, 310_000, 330_000, 350_000, 370_000, 390_000, 420_000],
          entity={"commenced": "2026-01-05", "gst_registered_on": "2026-01-20"},
          opex={"rent": 15_000, "salaries": [("COOK A", 16_000)], "utilities": 5_000, "transport": 4_000,
                "variable_ratio": 0.6},
          drawings=20_000, cash_share=0.02, paytm_share=0.55,
          other_credits=[(0, 5, "owner_contribution", "CAPITAL INTRODUCED-PROPRIETOR", 250_000)],
          itr=[], financials=None, missing_documents=["itr", "pnl", "balance_sheet", "cash_flow"]),
    _make("incomplete_docs", "Transport operator with missing paperwork",
          "Strong cash flow, but the latest ITR and the financial statements were never prepared.",
          _profile(borrower_name="Vetrivel Kumar", business_name="Vetri Logistics",
                   industry="transport_logistics", city="Salem", business_vintage_years=6.2,
                   requested_amount=1_200_000, monthly_revenue=1_050_000, monthly_expenses=800_000,
                   personal_monthly_income=120_000, previously_rejected=True, rejection_reason="documentation",
                   rejection_note="They kept asking for papers my accountant has not finished."),
          1_050_000, 5,
          opex={"variable_ratio": 0.64}, cash_share=0.08, paytm_share=0.05,
          loans=[_loan("v1", "Kurinji Asset Finance", "KURINJI AF", "Commercial vehicle loan", 1_400_000, 12, 48,
                       "2025-01", 5, True)],
          itr=[{"ay": "2025-26", "gross_receipts": 10_900_000, "net_income": 1_520_000}],
          financials=None, missing_documents=["pnl", "balance_sheet", "cash_flow"],
          rejection={"date": "2026-08-22", "lender": "Palani Hills Sahakari Bank (fictional)",
                     "product": "Business term loan", "amount": 1_200_000, "ref": "PHSB/BL/2026/000733",
                     "reason": "Application could not be processed: required financial documents were not provided."}),
    _make("collateral_backed", "Granite trader needing a large secured loan",
          "The amount is too large for unsecured products; a property-backed route may fit.",
          _profile(borrower_name="Meenakshi Sundaram", business_name="Meenakshi Granites & Tiles",
                   industry="construction", city="Hosur", business_vintage_years=11.0,
                   requested_amount=6_000_000, loan_purpose="business_expansion", monthly_revenue=1_400_000,
                   monthly_expenses=1_120_000, personal_monthly_income=150_000,
                   collateral="commercial_property", collateral_value=14_000_000),
          1_400_000, 6,
          opex={"variable_ratio": 0.66, "rent": 0}, drawings=80_000, cash_share=0.1, paytm_share=0.04,
          loans=[_loan("c1", "Vaigai Capital Finance", "VAIGAI CAP", "Unsecured business loan", 900_000, 18, 36,
                       "2025-06", 8)],
          collateral={"type": "commercial_property",
                      "description": "Showroom and yard, 2,400 sq ft, Bagalur Road, Hosur", "value": 14_000_000}),
]}


def scenario_from_profile(profile: dict[str, Any], seed_key: str) -> dict[str, Any]:
    """A synthetic document pack built around a borrower's own onboarding answers (for non-library cases).
    Documented receipts are set a little below what was declared, as is typical; nothing else is invented."""
    n = zlib.crc32(seed_key.encode()) % 9 + 1
    revenue = max(profile["monthly_revenue"], 50_000)
    ratio = min(0.92, max(0.5, (profile["monthly_expenses"] or revenue * 0.75) / revenue))
    emi_total = profile["monthly_emi"]
    loans = []
    count = min(profile["existing_loan_count"], 4)
    for i in range(count):
        principal = calc.principal_for_emi(max(profile["monthly_emi"] // count, 1_000), 18, 36)
        if principal >= 10_000:
            loans.append(_loan(f"x{i}", ["Vaigai Capital Finance", "Neithal Fincorp", "Kurinji Asset Finance",
                                         "Marutham Business Credit"][i],
                               ["VAIGAI CAP", "NEITHAL FIN", "KURINJI AF", "MARUTHAM BC"][i],
                               "Business loan", principal, 18, 36, "2025-11", 5 + i))
    registered = profile["gst_status"] == "registered"
    years = profile["business_vintage_years"]
    collateral = None
    if profile["collateral"] != "none" and profile.get("collateral_value"):
        collateral = {"type": profile["collateral"], "description": "As declared by the borrower",
                      "value": profile["collateral_value"]}
    scenario = _make(f"custom-{seed_key}", "Synthetic pack built from your answers", "Custom borrower.",
                     deepcopy(profile), round(revenue * 0.92), n, loans=loans, collateral=collateral,
                     opex={"rent": round(revenue * 0.03, -2), "utilities": round(revenue * 0.01, -2),
                           "transport": round(revenue * 0.015, -2), "variable_ratio": round(ratio - 0.135, 2),
                           "salaries": [("STAFF A", round(revenue * 0.045, -2)), ("STAFF B", round(revenue * 0.035, -2))]},
                     drawings=max(0, round((revenue * 0.92 * (1 - ratio) - emi_total) * 0.5, -2)),
                     bank={"opening_balance": round(revenue * 0.3, -3)})
    if not registered:
        scenario["gst"]["turnover"] = None
    if years < 1.5:
        scenario["itr"], scenario["financials"] = [], None
        scenario["missing_documents"] = ["itr", "pnl", "balance_sheet", "cash_flow"]
    return scenario


# --------------------------------------------------------------------------------------------- dataset

def _loan_view(loan: dict[str, Any], bounces: set[tuple[str, str]]) -> dict[str, Any]:
    schedule = calc.amortisation_schedule(loan["principal"], loan["rate"], loan["tenure"])
    rows = []
    for row in schedule:
        ym = month_add(loan["first_emi"], row["month"] - 1)
        due = _date(ym, loan["emi_day"])
        bounced = (ym, loan["key"]) in bounces
        status = "Due" if due > AS_OF else ("Returned, paid late" if bounced else "Paid")
        rows.append({**row, "ym": ym, "due_date": due, "status": status,
                     "paid_date": None if due > AS_OF else (_date(ym, loan["emi_day"] + 7) if bounced else due),
                     "days_past_due": 7 if bounced and due <= AS_OF else 0})
    paid = sum(1 for r in rows if r["due_date"] <= AS_OF)
    return {**loan, "emi": schedule[0]["emi"], "disbursed": _date(month_add(loan["first_emi"], -1), 18),
            "paid": paid, "remaining": loan["tenure"] - paid,
            "outstanding": rows[paid - 1]["closing"] if paid else loan["principal"],
            "status": "Closed" if paid == loan["tenure"] else "Active", "schedule": rows}


def build_dataset(scenario: dict[str, Any]) -> dict[str, Any]:
    s = deepcopy(scenario)
    rng = random.Random(zlib.crc32(s["id"].encode()))
    bounces = {(MONTHS[m], key) for m, key in s["bounces"]}
    loans = [_loan_view(loan, bounces) for loan in s["loans"]]
    gst_cfg, opex, bank = s["gst"], s["opex"], s["bank"]
    turnover = gst_cfg["turnover"]

    # GST returns first: the tax paid shows up in the following month's bank statement.
    returns = []
    for i, ym in enumerate(MONTHS if turnover else []):
        if ym < s["entity"]["gst_registered_on"][:7]:
            continue                                   # not yet registered: no return for this month
        taxable = turnover[i]
        tax = round(taxable * gst_cfg["rate"] / 100)
        igst = round(tax * 0.3 / 2) * 2
        itc = round(tax * 0.85)
        late = gst_cfg["late"].get(i, 0)
        nxt = month_add(ym, 1)
        b2b = round(taxable * 0.7 / 1000) * 1000
        returns.append({
            "month": ym, "taxable": taxable, "igst": igst, "cgst": (tax - igst) // 2, "sgst": (tax - igst) // 2,
            "tax": tax, "itc": itc, "net_cash": tax - itc, "due": _date(nxt, 20), "filed": _date(nxt, 20 + late) if late
            else _date(nxt, 18), "days_late": late, "late_fee": late * 50, "arn": f"AA33{ym[5:]}{ym[2:4]}{i:07d}Z",
            "gstr1_due": _date(nxt, 11), "gstr1_filed": _date(nxt, 10), "b2b_count": 6 + rng.randrange(8),
            "b2b_value": b2b, "b2c_value": taxable - b2b,
        })

    statements, truth_months, balance, seq = [], [], bank["opening_balance"], 0
    waiting: list[tuple[int, int, str, int, int, str]] = []   # discretionary payments held back for lack of funds
    paytm_months = []
    for i, ym in enumerate(MONTHS):
        rows: list[tuple[int, int, str, int, int, str]] = []   # day, order, narration, debit, credit, category
        receipts = s["receipts"][i]
        cash = round(receipts * s["cash_share"] / 1000) * 1000
        paytm = round(receipts * s["paytm_share"] / 100) * 100
        transfers = receipts - cash - paytm
        if cash:
            for amount in _split(cash, 7, rng, 500):
                rows.append((rng.randint(1, 26), 0, f"CASH DEP-{bank['branch'].upper()}-SELF", 0, amount,
                             "business_receipt"))
        settlements = _split(paytm, 8, rng) if paytm else []
        for amount in settlements:
            day = rng.randint(1, 28)
            rows.append((day, 0, f"PAYTM SETTLEMENT-{s['entity']['paytm_mid']}-{day:02d}{ym[5:]}", 0, amount,
                         "business_receipt"))
        if transfers:
            for k, amount in enumerate(_split(transfers, 9, rng)):
                mode = "RTGS" if amount >= 200_000 else ("NEFT", "IMPS", "UPI")[k % 3]
                rows.append((rng.randint(1, 28), 0,
                             f"{mode} CR-{s['buyers'][rng.randrange(len(s['buyers']))]}-INV {i * 40 + k + 101}", 0, amount,
                             "business_receipt"))
        for m, day, category, narration, amount in s["other_credits"]:
            if m == i:
                rows.append((day, 0, narration, 0, amount, category))

        by_month = {r["month"]: r for r in returns}
        prev = by_month.get(MONTHS[i - 1]) if i else None
        gst_paid = (prev["net_cash"] + prev["late_fee"]) if prev else (
            round(by_month[ym]["net_cash"] * 0.97) if i == 0 and ym in by_month else 0)
        fixed = [(10, "RENT-GODOWN-V SUNDARAM", opex["rent"]), (15, "EB BILL-TN POWER DISCOM", opex["utilities"]),
                 (8, "FREIGHT-SRS PARCEL SERVICE", opex["transport"] // 2),
                 (21, "FREIGHT-SRS PARCEL SERVICE", opex["transport"] - opex["transport"] // 2)]
        fixed += [(28, f"SALARY-{name}", amount) for name, amount in opex["salaries"]]
        if gst_paid:
            day = 20 + (prev["days_late"] if prev else 0)
            fixed.append((day, f"GST PMT-CPIN {ym[2:4]}{ym[5:]}33{i:06d}", gst_paid))
        if receipts:
            for day, narration, amount in fixed:
                if amount:
                    rows.append((day, 1, narration, amount, 0, "operating_expense"))
            variable = round(receipts * opex["variable_ratio"] / 100) * 100
            for k, amount in enumerate(_split(variable, 8, rng)):
                mode = "RTGS" if amount >= 200_000 else "NEFT"
                rows.append((rng.randint(9, 28), 1, f"{mode} DR-{s['suppliers'][k % len(s['suppliers'])]}-PURCHASE", amount, 0,
                             "operating_expense"))
            rows.append((16, 1, f"IMPS DR-{s['profile']['borrower_name'].upper()}-SELF DRAWINGS", s["drawings"], 0,
                         "owner_drawings"))

        for loan in loans:
            if loan["disbursed"][:7] == ym:
                rows.append((18, 0, f"LOAN DISB-{loan['short']}-{loan['account_no']}", 0, loan["principal"],
                             "loan_disbursement"))
            for inst in loan["schedule"]:
                if inst["ym"] != ym:
                    continue
                narration = f"ACH D-{loan['short']}-{loan['account_no']}"
                if inst["status"] == "Returned, paid late":
                    rows.append((loan["emi_day"], 1, f"ACH RTN CHGS-{loan['short']}-{loan['account_no']}", 590, 0,
                                 "bounce_charge"))
                    rows.append((loan["emi_day"] + 7, 1, f"{narration}-REPRESENT", inst["emi"], 0, "loan_repayment"))
                else:
                    rows.append((loan["emi_day"], 1, narration, inst["emi"], 0, "loan_repayment"))
        for m, day, category, narration, amount in s["other_debits"]:
            if m == i:
                rows.append((day, 1, narration, amount, 0, category))

        rows.sort(key=lambda r: (r[0], r[1]))
        opening, transactions = balance, []
        totals: dict[str, int] = {}
        committed = sum(r[3] for r in rows if r[5] in ("loan_repayment", "bounce_charge"))   # EMIs still to come

        def post(day: int, narration: str, debit: int, credit: int, category: str) -> None:
            nonlocal balance, seq
            seq += 1
            balance += credit - debit
            totals[category] = totals.get(category, 0) + credit + debit
            transactions.append({"date": _date(ym, day), "narration": narration, "ref": f"{ym[2:4]}{ym[5:]}{seq:06d}",
                                 "debit": debit, "credit": credit, "balance": balance, "category": category})

        for row in rows:
            day, _, narration, debit, credit, category = row
            if category in ("loan_repayment", "bounce_charge"):
                committed -= debit
            elif debit and debit > balance - committed:       # would eat into money needed for this month's EMIs
                waiting.append(row)
                continue
            post(day, narration, debit, credit, category)
            for held in list(waiting) if credit else []:
                if held[3] <= balance - committed:
                    waiting.remove(held)
                    post(day, held[2], held[3], 0, held[5])
        if i == len(MONTHS) - 1:
            for held in waiting:
                post(31, held[2], held[3], 0, held[5])
        statements.append({"month": ym, "opening_balance": opening, "closing_balance": balance,
                           "transactions": transactions})
        truth_months.append({
            "month": ym, "total_credits": sum(t["credit"] for t in transactions),
            "total_debits": sum(t["debit"] for t in transactions),
            "business_receipts": totals.get("business_receipt", 0), "cash_deposits": cash,
            "operating_expenses": totals.get("operating_expense", 0),
            "loan_repayments": totals.get("loan_repayment", 0), "owner_drawings": totals.get("owner_drawings", 0),
            "closing_balance": balance,
        })
        gross = [round(a / 0.976) for a in settlements]
        fees = [round(g * 0.009) for g in gross]
        paytm_months.append({"month": ym, "gross_collections": sum(gross), "fees": sum(fees),
                             "refunds": sum(gross) - sum(fees) - sum(settlements),
                             "net_settlements": sum(settlements), "settlement_count": len(settlements)})

    active = [loan for loan in loans if loan["status"] == "Active"]
    n = len(MONTHS)
    truth = {
        "monthly": truth_months,
        "avg_total_credits": round(sum(m["total_credits"] for m in truth_months) / n),
        "avg_business_receipts": round(sum(m["business_receipts"] for m in truth_months) / n),
        "avg_operating_expenses": round(sum(m["operating_expenses"] for m in truth_months) / n),
        "avg_gst_turnover": round(sum(r["taxable"] for r in returns) / len(returns)) if returns else None,
        "emi_returns": len(bounces), "late_gst_filings": len(gst_cfg["late"]) if turnover else 0,
        "active_emi_total": sum(loan["emi"] for loan in active),
        "active_outstanding_total": sum(loan["outstanding"] for loan in active),
        "non_business_credits": sum(a for *_, a in s["other_credits"])
        + sum(loan["principal"] for loan in loans if loan["disbursed"][:7] in MONTHS),
        "deliberate_discrepancies": s["tests"],
    }
    # The declared liabilities in the profile follow the loan documents, so only the intended gaps remain.
    profile = s["profile"]
    if s["id"] in SCENARIOS:
        profile.update(existing_loan_count=len(active), outstanding_loan_amount=truth["active_outstanding_total"],
                       monthly_emi=truth["active_emi_total"])

    return {
        "scenario_id": s["id"], "title": s["title"], "as_of": AS_OF, "months": MONTHS, "profile": profile,
        "entity": s["entity"], "bank": {**bank, "statements": statements},
        "gst": {"registered": bool(turnover), "rate": gst_cfg["rate"], "returns": returns},
        "itr": s["itr"], "loans": loans, "financials": _financials(s, loans, statements),
        "rejection": s["rejection"], "collateral": s["collateral"], "missing_documents": s["missing_documents"],
        "paytm": {"merchant_id": s["entity"]["paytm_mid"], "monthly": paytm_months},
        "truth": truth,
    }


def _financials(s: dict[str, Any], loans: list[dict[str, Any]], statements: list[dict[str, Any]]
                ) -> dict[str, Any] | None:
    """P&L, balance sheet and cash-flow statement for FY 2025-26, tied to the latest ITR and the loan schedules."""
    f = s["financials"]
    if not f or not s["itr"]:
        return None
    itr, opex = s["itr"][-1], s["opex"]
    in_fy = [r for loan in loans for r in loan["schedule"] if FY_START <= r["ym"] <= FY_END]
    interest, principal_repaid = sum(r["interest"] for r in in_fy), sum(r["principal"] for r in in_fy)
    loans_taken = sum(loan["principal"] for loan in loans if FY_START <= loan["disbursed"][:7] <= FY_END)

    def outstanding(loan: dict[str, Any]) -> int:
        if loan["disbursed"][:7] > FY_END:
            return 0
        done = [r for r in loan["schedule"] if r["ym"] <= FY_END]
        return done[-1]["closing"] if done else loan["principal"]

    revenue, net = itr["gross_receipts"], itr["net_income"]
    salaries, rent = 12 * sum(a for _, a in opex["salaries"]), 12 * opex["rent"]
    power, freight = 12 * opex["utilities"], 12 * opex["transport"]
    overheads = salaries + rent + power + freight + interest + f["depreciation"] + f["other_expenses"]
    cogs = revenue - overheads - net
    pnl = {"revenue": revenue, "cost_of_goods_sold": cogs, "gross_profit": revenue - cogs, "salaries": salaries,
           "rent": rent, "power": power, "freight": freight, "interest": interest,
           "depreciation": f["depreciation"], "other_expenses": f["other_expenses"], "net_profit": net}

    bank_balance = next(st["closing_balance"] for st in statements if st["month"] == FY_END)
    secured = sum(outstanding(loan) for loan in loans if loan["secured"])
    unsecured = sum(outstanding(loan) for loan in loans if not loan["secured"])
    assets = f["fixed_assets"] + f["stock"] + f["debtors"] + bank_balance + f["cash_in_hand"]
    balance_sheet = {"capital": assets - secured - unsecured - f["creditors"], "secured_loans": secured,
                     "unsecured_loans": unsecured, "creditors": f["creditors"], "total_liabilities": assets,
                     "fixed_assets": f["fixed_assets"], "stock": f["stock"], "debtors": f["debtors"],
                     "bank_balance": bank_balance, "cash_in_hand": f["cash_in_hand"], "total_assets": assets}

    closing_cash = bank_balance + f["cash_in_hand"]
    drawings = 12 * s["drawings"]
    # Increase in working capital is the balancing figure (negative means working capital was released).
    wc_increase = (net + f["depreciation"] - f["capex"] + loans_taken - principal_repaid - drawings
                   - (closing_cash - f["opening_cash"]))
    operating = net + f["depreciation"] + interest - wc_increase
    cash_flow = {"net_profit": net, "depreciation": f["depreciation"], "interest_added_back": interest,
                 "working_capital_increase": wc_increase, "cash_from_operations": operating,
                 "capital_expenditure": f["capex"], "loans_taken": loans_taken,
                 "loan_principal_repaid": principal_repaid, "interest_paid": interest, "owner_drawings": drawings,
                 "net_change_in_cash": closing_cash - f["opening_cash"], "opening_cash": f["opening_cash"],
                 "closing_cash": closing_cash}
    return {"fy": FY_LABEL, "ay": FY_AY, "pnl": pnl, "balance_sheet": balance_sheet, "cash_flow": cash_flow}
