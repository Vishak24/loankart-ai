"""Financial engine tests. Expected values were computed independently of app.calculations
(closed-form EMI evaluated separately, schedules worked by hand), never by calling the function under test."""

import pytest

from app import calculations as calc


@pytest.mark.parametrize("principal, rate, months, expected", [
    (1_000_000, 12, 12, 88_849),      # 88,848.79
    (100_000, 12, 12, 8_885),         # 8,884.88
    (2_500_000, 9, 240, 22_493),      # 22,493.15
    (500_000, 10.5, 60, 10_747),      # 10,746.95
    (750_000, 21, 36, 28_256),        # 28,256.30
    (1_500_000, 18, 36, 54_229),      # 54,228.59
    (120_000, 0, 12, 10_000),         # zero-rate loan
    (100_000, 12, 1, 101_000),        # single instalment: principal + one month's interest
])
def test_emi(principal, rate, months, expected):
    assert calc.emi(principal, rate, months) == expected


@pytest.mark.parametrize("args", [(0, 12, 12), (-5, 12, 12), (1000, -1, 12), (1000, 101, 12), (1000, 12, 0),
                                  (1000, 12, 1.5), (1000, 12, 481), (True, 12, 12)])
def test_emi_rejects_invalid_inputs(args):
    with pytest.raises(ValueError):
        calc.emi(*args)


def test_emi_rounds_half_up():
    assert calc.rupees("0.5") == 1 and calc.rupees("1.5") == 2 and calc.rupees("2.4999") == 2


def test_amortisation_schedule_worked_by_hand():
    # 1,00,000 at 12% for 3 months. r = 1%. EMI = 34,002.21 -> 34,002.
    # m1: interest 1,000, principal 33,002, closing 66,998
    # m2: interest 670 (669.98), principal 33,332, closing 33,666
    # m3: interest 337 (336.66), principal 33,666 (clears balance), instalment 34,003
    rows = calc.amortisation_schedule(100_000, 12, 3)
    assert [(r["interest"], r["principal"], r["closing"]) for r in rows] == [
        (1_000, 33_002, 66_998), (670, 33_332, 33_666), (337, 33_666, 0)]
    assert [r["emi"] for r in rows] == [34_002, 34_002, 34_003]


def test_schedule_always_clears_and_principal_sums():
    for principal, rate, months in [(1_500_000, 18, 36), (650_000, 11.5, 36), (99_999, 23.75, 7), (10, 12, 12)]:
        rows = calc.amortisation_schedule(principal, rate, months)
        assert len(rows) == months and rows[-1]["closing"] == 0
        assert sum(r["principal"] for r in rows) == principal
        assert all(r["opening"] - r["principal"] == r["closing"] for r in rows)


def test_total_interest_and_repayment():
    cost = calc.loan_cost(100_000, 12, 3)
    assert cost == {"emi": 34_002, "total_repayment": 102_007, "total_interest": 2_007}
    # 10,00,000 at 12% for 12 months: 12 x 88,848.79 = 10,66,185.46 -> within a few rupees after rounding
    cost = calc.loan_cost(1_000_000, 12, 12)
    assert abs(cost["total_repayment"] - 1_066_185) <= 6
    assert cost["total_interest"] == cost["total_repayment"] - 1_000_000


def test_outstanding_after():
    assert calc.outstanding_after(100_000, 12, 3, 0) == 100_000
    assert calc.outstanding_after(100_000, 12, 3, 1) == 66_998
    assert calc.outstanding_after(100_000, 12, 3, 3) == 0
    with pytest.raises(ValueError):
        calc.outstanding_after(100_000, 12, 3, 4)


def test_interest_only_payment():
    assert calc.interest_only_payment(1_500_000, 14) == 17_500   # 15,00,000 x 14% / 12
    assert calc.interest_only_payment(840_000, 11.5) == 8_050


def test_principal_for_emi_is_inverse_of_emi():
    p = calc.principal_for_emi(54_229, 18, 36)
    assert 1_499_950 <= p <= 1_500_050                            # 54,229 is the EMI of 15,00,000
    assert calc.emi(p, 18, 36) <= 54_229 < calc.emi(p + 100, 18, 36) + 4
    assert calc.principal_for_emi(0, 18, 36) == 0
    assert calc.principal_for_emi(10_000, 0, 12) == 120_000


def test_foir():
    assert calc.foir(48_500, 60_000) == 80.83                     # 80.8333
    assert calc.foir(0, 60_000) == 0.0
    assert calc.foir(30_000, 60_000) == 50.0                      # boundary value used by policies
    for bad in [(1, 0), (1, -5), (-1, 100)]:
        with pytest.raises(ValueError):
            calc.foir(*bad)


def test_dscr():
    assert calc.dscr(75_000, 50_000) == 1.5
    assert calc.dscr(74_250, 103_919) == 0.71                     # 0.7145
    assert calc.dscr(60_000, 50_000) == 1.2                       # boundary
    assert calc.dscr(-10_000, 50_000) == -0.2                     # loss-making month stays negative
    assert calc.dscr(75_000, 0) is None
    with pytest.raises(ValueError):
        calc.dscr(1, -1)


def test_ltv():
    assert calc.ltv(840_000, 1_120_000) == 75.0
    assert calc.ltv(6_000_000, 14_000_000) == 42.86
    with pytest.raises(ValueError):
        calc.ltv(1, 0)


def test_debt_to_income():
    assert calc.debt_to_income(980_000, 720_000) == 1.36
    with pytest.raises(ValueError):
        calc.debt_to_income(1, 0)


def test_repayment_capacity_and_dscr_room():
    assert calc.repayment_capacity(100_000, 50, 30_000) == 20_000
    assert calc.repayment_capacity(100_000, 50, 60_000) == 0       # already over the ceiling: no room, not negative
    assert calc.max_service_for_dscr(75_000, 1.25, 50_000) == 10_000
    assert calc.max_service_for_dscr(75_000, 1.25, 70_000) == 0
    with pytest.raises(ValueError):
        calc.max_service_for_dscr(1, 0, 0)


def test_apr():
    assert calc.apr(100_000, 12, 12) == pytest.approx(12.0, abs=0.02)        # no fees: APR equals the rate
    assert calc.apr(100_000, 12, 12, upfront_fees=2_000) > 15.5              # 2% fee on a 1-year loan adds ~3.8 points
    assert calc.apr(100_000, 12, 12, upfront_fees=2_000) < 16.2
    assert calc.apr(1_000_000, 12, 12, interest_only=True) == pytest.approx(12.0, abs=0.02)
    with pytest.raises(ValueError):
        calc.apr(100_000, 12, 12, upfront_fees=100_000)


def test_monthly_cash_flow():
    months = [{"business_receipts": 400_000, "operating_expenses": 330_000, "loan_repayments": 50_000},
              {"business_receipts": 500_000, "operating_expenses": 410_000, "loan_repayments": 50_000}]
    assert calc.monthly_cash_flow(months) == {
        "avg_business_receipts": 450_000, "avg_operating_expenses": 370_000, "avg_operating_surplus": 80_000,
        "avg_loan_repayments": 50_000, "avg_free_cash": 30_000}
    with pytest.raises(ValueError):
        calc.monthly_cash_flow([])


def test_loan_amount_change_before_after():
    # Halving the amount halves the EMI (to the rupee) at the same rate and tenure.
    assert calc.emi(1_500_000, 18, 36) == 54_229 and calc.emi(750_000, 18, 36) == 27_114


def test_tenure_change_lowers_emi_but_raises_total_interest():
    short, long = calc.loan_cost(1_500_000, 18, 36), calc.loan_cost(1_500_000, 18, 60)
    assert long["emi"] == 38_090                                   # 38,090.14
    assert long["emi"] < short["emi"] and long["total_interest"] > short["total_interest"]


def test_liability_restructuring():
    # Outstanding 5,00,000 with 22 EMIs of 28,256 left, moved to 16% over 48 months, 1% fee.
    r = calc.refinance(500_000, 16, 48, 28_256, 22, fee_pct=1)
    assert r["new_emi"] == 14_170                                  # 14,170.14
    assert r["monthly_relief"] == 14_086
    assert r["old_remaining_total"] == 621_632 and r["fee"] == 5_000
    assert r["extra_cost"] == r["new_total"] - 621_632 and r["extra_cost"] > 50_000   # relief costs more overall
