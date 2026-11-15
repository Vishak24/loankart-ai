"""Deterministic financial engine. The only place authoritative loan figures are computed.

All arithmetic is Decimal. Rupee amounts are rounded half-up to whole rupees; ratios to 2 decimals.
No function here applies a lending threshold: thresholds belong to each lender's policy (lenders.json).

Formulas (r = annual rate / 1200, n = months, P = principal):
  EMI                 = P * r * (1+r)^n / ((1+r)^n - 1)          (P / n when r = 0)
  Interest in month k = opening balance * r                      (rounded to the rupee)
  Last instalment     = remaining balance + that month's interest (absorbs rounding)
  Interest-only pay   = P * r
  Principal for EMI   = E * ((1+r)^n - 1) / (r * (1+r)^n)        (inverse of EMI, floored)
  FOIR %              = monthly obligations / assessed monthly income * 100
  DSCR                = monthly operating surplus before debt service / monthly debt service
  LTV %               = loan amount / collateral value * 100
  APR %               = annualised monthly IRR of (P - upfront fees) against the repayments
"""

from decimal import ROUND_DOWN, ROUND_HALF_UP, Decimal, getcontext
from typing import Any

getcontext().prec = 28
Number = int | float | str | Decimal


def _d(x: Number) -> Decimal:
    if isinstance(x, bool):
        raise ValueError("boolean is not a number")
    return x if isinstance(x, Decimal) else Decimal(str(x))


def rupees(x: Number) -> int:
    return int(_d(x).quantize(Decimal("1"), ROUND_HALF_UP))


def ratio(x: Number) -> float:
    """2-decimal ratio for API output (computed in Decimal, serialised as a JSON number)."""
    return float(_d(x).quantize(Decimal("0.01"), ROUND_HALF_UP))


def _check_loan(principal: Number, annual_rate_pct: Number, months: int) -> tuple[Decimal, Decimal, int]:
    p, rate = _d(principal), _d(annual_rate_pct)
    if p <= 0:
        raise ValueError("principal must be greater than 0")
    if rate < 0 or rate > 100:
        raise ValueError("annual_rate_pct must be between 0 and 100")
    if isinstance(months, bool) or not isinstance(months, int) or months < 1 or months > 480:
        raise ValueError("months must be a whole number between 1 and 480")
    return p, rate / Decimal(1200), months


def emi(principal: Number, annual_rate_pct: Number, months: int) -> int:
    p, r, n = _check_loan(principal, annual_rate_pct, months)
    if r == 0:
        return rupees(p / n)
    growth = (1 + r) ** n
    return rupees(p * r * growth / (growth - 1))


def amortisation_schedule(principal: Number, annual_rate_pct: Number, months: int) -> list[dict[str, int]]:
    p, r, n = _check_loan(principal, annual_rate_pct, months)
    instalment, balance, rows = emi(p, annual_rate_pct, n), rupees(p), []
    for k in range(1, n + 1):
        interest = rupees(balance * r)
        principal_part = balance if k == n else min(balance, instalment - interest)
        rows.append({
            "month": k, "opening": balance, "emi": principal_part + interest,
            "interest": interest, "principal": principal_part, "closing": balance - principal_part,
        })
        balance -= principal_part
    return rows


def loan_cost(principal: Number, annual_rate_pct: Number, months: int) -> dict[str, int]:
    """EMI, total repayment and total interest, taken from the actual schedule (so they include rounding)."""
    schedule = amortisation_schedule(principal, annual_rate_pct, months)
    total = sum(row["emi"] for row in schedule)
    return {"emi": schedule[0]["emi"] if months > 1 else total, "total_repayment": total,
            "total_interest": total - rupees(principal)}


def outstanding_after(principal: Number, annual_rate_pct: Number, months: int, instalments_paid: int) -> int:
    if instalments_paid < 0 or instalments_paid > months:
        raise ValueError("instalments_paid must be between 0 and months")
    if instalments_paid == 0:
        return rupees(principal)
    return amortisation_schedule(principal, annual_rate_pct, months)[instalments_paid - 1]["closing"]


def interest_only_payment(principal: Number, annual_rate_pct: Number) -> int:
    p, r, _ = _check_loan(principal, annual_rate_pct, 1)
    return rupees(p * r)


def principal_for_emi(max_emi: Number, annual_rate_pct: Number, months: int) -> int:
    """Largest principal whose EMI does not exceed max_emi."""
    e = _d(max_emi)
    if e <= 0:
        return 0
    _, r, n = _check_loan(1, annual_rate_pct, months)
    if r == 0:
        return int((e * n).quantize(Decimal("1"), ROUND_DOWN))
    growth = (1 + r) ** n
    p = int((e * (growth - 1) / (r * growth)).quantize(Decimal("1"), ROUND_DOWN))
    while p > 0 and emi(p, annual_rate_pct, n) > e:  # rounding guard
        p -= 1
    return p


def foir(monthly_obligations: Number, monthly_income: Number) -> float:
    income = _d(monthly_income)
    if income <= 0:
        raise ValueError("monthly_income must be greater than 0 to compute FOIR")
    if _d(monthly_obligations) < 0:
        raise ValueError("monthly_obligations cannot be negative")
    return ratio(_d(monthly_obligations) / income * 100)


def dscr(monthly_operating_surplus: Number, monthly_debt_service: Number) -> float | None:
    """None when there is no debt service (the ratio is undefined, not infinite)."""
    service = _d(monthly_debt_service)
    if service < 0:
        raise ValueError("monthly_debt_service cannot be negative")
    return None if service == 0 else ratio(_d(monthly_operating_surplus) / service)


def ltv(loan_amount: Number, collateral_value: Number) -> float:
    value = _d(collateral_value)
    if value <= 0:
        raise ValueError("collateral_value must be greater than 0 to compute LTV")
    return ratio(_d(loan_amount) / value * 100)


def debt_to_income(total_outstanding: Number, annual_income: Number) -> float:
    income = _d(annual_income)
    if income <= 0:
        raise ValueError("annual_income must be greater than 0")
    return ratio(_d(total_outstanding) / income)


def repayment_capacity(monthly_income: Number, max_foir_pct: Number, existing_obligations: Number) -> int:
    """Room for a new monthly instalment under a FOIR ceiling. Never negative."""
    room = _d(monthly_income) * _d(max_foir_pct) / 100 - _d(existing_obligations)
    return max(0, int(room.quantize(Decimal("1"), ROUND_DOWN)))


def max_service_for_dscr(monthly_operating_surplus: Number, min_dscr: Number, existing_service: Number) -> int:
    """Room for new monthly debt service while keeping DSCR at or above min_dscr. Never negative."""
    if _d(min_dscr) <= 0:
        raise ValueError("min_dscr must be greater than 0")
    room = _d(monthly_operating_surplus) / _d(min_dscr) - _d(existing_service)
    return max(0, int(room.quantize(Decimal("1"), ROUND_DOWN)))


def apr(principal: Number, annual_rate_pct: Number, months: int, upfront_fees: Number = 0,
        interest_only: bool = False) -> float:
    """Annual cost of credit including upfront charges (nominal: monthly IRR x 12), by bisection."""
    p, _, n = _check_loan(principal, annual_rate_pct, months)
    net = p - _d(upfront_fees)
    if net <= 0:
        raise ValueError("upfront_fees must be less than the principal")
    if interest_only:
        pay = interest_only_payment(p, annual_rate_pct)
        flows = [Decimal(pay)] * (n - 1) + [Decimal(pay) + p]
    else:
        flows = [Decimal(row["emi"]) for row in amortisation_schedule(p, annual_rate_pct, n)]
    lo, hi = Decimal(0), Decimal(1)
    for _ in range(80):
        mid = (lo + hi) / 2
        pv = sum(f / (1 + mid) ** k for k, f in enumerate(flows, 1))
        lo, hi = (mid, hi) if pv > net else (lo, mid)
    return ratio(lo * 1200)


def monthly_cash_flow(months: list[dict[str, Any]]) -> dict[str, int]:
    """Averages over rows of {business_receipts, operating_expenses, loan_repayments}."""
    if not months:
        raise ValueError("at least one month is required")
    n = len(months)
    receipts = rupees(sum(_d(m["business_receipts"]) for m in months) / n)
    expenses = rupees(sum(_d(m["operating_expenses"]) for m in months) / n)
    repayments = rupees(sum(_d(m["loan_repayments"]) for m in months) / n)
    return {"avg_business_receipts": receipts, "avg_operating_expenses": expenses,
            "avg_operating_surplus": receipts - expenses, "avg_loan_repayments": repayments,
            "avg_free_cash": receipts - expenses - repayments}


def refinance(outstanding: Number, new_rate_pct: Number, new_months: int, old_emi: Number,
              old_remaining_months: int, fee_pct: Number = 0) -> dict[str, int]:
    """Liability restructuring: replace the remaining instalments of a loan with a new loan for the outstanding
    balance. Shows the monthly relief together with the change in total cost, so one cannot hide the other."""
    new = loan_cost(outstanding, new_rate_pct, new_months)
    fee = rupees(_d(outstanding) * _d(fee_pct) / 100)
    old_total = rupees(_d(old_emi) * old_remaining_months)
    return {"old_emi": rupees(old_emi), "new_emi": new["emi"], "monthly_relief": rupees(old_emi) - new["emi"],
            "old_remaining_total": old_total, "new_total": new["total_repayment"] + fee, "fee": fee,
            "extra_cost": new["total_repayment"] + fee - old_total}
