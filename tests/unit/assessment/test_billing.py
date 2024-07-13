from datetime import date
from decimal import Decimal

import pytest

from headgate.assessment.billing import Bill, BillRun, ChargeKind, Line, bill_account
from headgate.assessment.tiers import Band, RateSchedule
from headgate.errors import PolicyError, ValidationError
from headgate.ids import AccountNumber
from headgate.money import Money

ISSUED = date(2025, 11, 1)


def schedule(water_year: int = 2025) -> RateSchedule:
    return RateSchedule(
        water_year=water_year,
        per_share=Money.from_dollars("4.50"),
        bands=(
            Band(Decimal("50"), Money.from_dollars("2.00")),
            Band(Decimal("150"), Money.from_dollars("3.50")),
            Band(None, Money.from_dollars("6.00")),
        ),
    )


def bill(**overrides: object) -> Bill:
    fields: dict[str, object] = {
        "account": AccountNumber(118),
        "water_year": 2025,
        "issued_on": ISSUED,
        "schedule": schedule(),
        "shares": Decimal("20"),
        "delivered_af": Decimal("50"),
    }
    fields.update(overrides)
    return bill_account(**fields)  # type: ignore[arg-type]


def test_a_bill_charges_shares_and_water_on_separate_lines() -> None:
    built = bill()
    assert built.line_for(ChargeKind.SHARES) is not None
    assert built.line_for(ChargeKind.WATER) is not None
    assert built.total == Money.from_dollars("190.00")


def test_an_account_that_took_no_water_still_pays_for_its_shares() -> None:
    built = bill(delivered_af=Decimal("0"))
    assert built.line_for(ChargeKind.WATER) is None
    assert built.total == Money.from_dollars("90.00")


def test_ditch_loss_is_billed_at_the_rate_above_the_delivery() -> None:
    built = bill(loss_af=Decimal("10"))
    loss_line = built.line_for(ChargeKind.DITCH_LOSS)
    assert loss_line is not None
    assert loss_line.amount == Money.from_dollars("35.00")


def test_ditch_loss_climbs_the_bands_the_same_way_water_does() -> None:
    near_top = bill(delivered_af=Decimal("145"), loss_af=Decimal("10"))
    loss_line = near_top.line_for(ChargeKind.DITCH_LOSS)
    assert loss_line is not None
    assert loss_line.amount > Money.from_dollars("35.00")


def test_a_penalty_goes_on_its_own_line() -> None:
    built = bill(penalty=Money.from_dollars("12.50"))
    penalty = built.line_for(ChargeKind.PENALTY)
    assert penalty is not None
    assert built.total == Money.from_dollars("202.50")


def test_a_credit_comes_off_the_total() -> None:
    built = bill(credit=Money.from_dollars("40.00"))
    assert built.credits == Money.from_dollars("-40.00")
    assert built.total == Money.from_dollars("150.00")


def test_a_credit_larger_than_the_bill_leaves_the_account_in_credit() -> None:
    built = bill(credit=Money.from_dollars("400.00"))
    assert built.in_credit
    assert built.total.cents < 0


def test_charges_and_credits_are_reported_apart() -> None:
    built = bill(credit=Money.from_dollars("40.00"))
    assert built.charges == Money.from_dollars("190.00")
    assert built.credits == Money.from_dollars("-40.00")


def test_a_credit_that_adds_to_the_bill_is_refused() -> None:
    with pytest.raises(ValidationError, match="is not a credit"):
        Line(ChargeKind.CREDIT, "wrong way round", Decimal("0"), Money.from_dollars("10.00"))


def test_a_negative_charge_is_refused() -> None:
    with pytest.raises(ValidationError, match="may not be negative"):
        Line(ChargeKind.WATER, "wrong way round", Decimal("0"), Money.from_dollars("-10.00"))


def test_a_schedule_from_another_year_cannot_bill_this_one() -> None:
    with pytest.raises(PolicyError, match="cannot bill"):
        bill(schedule=schedule(2024))


def test_negative_water_cannot_be_billed() -> None:
    with pytest.raises(ValidationError, match="negative water"):
        bill(delivered_af=Decimal("-1"))


def test_a_run_totals_its_bills() -> None:
    run = BillRun(
        water_year=2025,
        issued_on=ISSUED,
        bills=(bill(), bill(account=AccountNumber(212), shares=Decimal("4"))),
    )
    assert (
        run.total == run.bill_for(AccountNumber(118)).total + run.bill_for(AccountNumber(212)).total
    )


def test_a_run_lists_its_accounts_in_order() -> None:
    run = BillRun(
        water_year=2025,
        issued_on=ISSUED,
        bills=(bill(account=AccountNumber(212)), bill()),
    )
    assert run.accounts == (AccountNumber(118), AccountNumber(212))


def test_an_account_billed_twice_in_one_run_is_refused() -> None:
    with pytest.raises(ValidationError, match="billed twice"):
        BillRun(water_year=2025, issued_on=ISSUED, bills=(bill(), bill()))


def test_a_bill_from_another_year_cannot_join_the_run() -> None:
    other = bill_account(
        account=AccountNumber(212),
        water_year=2024,
        issued_on=ISSUED,
        schedule=schedule(2024),
        shares=Decimal("4"),
        delivered_af=Decimal("10"),
    )
    with pytest.raises(ValidationError, match="turned up in the"):
        BillRun(water_year=2025, issued_on=ISSUED, bills=(bill(), other))


def test_asking_for_an_account_that_was_not_billed_is_refused() -> None:
    run = BillRun(water_year=2025, issued_on=ISSUED, bills=(bill(),))
    with pytest.raises(PolicyError, match="was not in the"):
        run.bill_for(AccountNumber(999))


def test_the_accounts_in_credit_are_listed() -> None:
    run = BillRun(
        water_year=2025,
        issued_on=ISSUED,
        bills=(
            bill(),
            bill(account=AccountNumber(212), credit=Money.from_dollars("400.00")),
        ),
    )
    assert [item.account for item in run.in_credit] == [AccountNumber(212)]
