from datetime import date
from decimal import Decimal

import pytest

from headgate.assessment.billing import Bill, bill_account
from headgate.assessment.payment import (
    AccountLedger,
    Payment,
    PaymentMethod,
)
from headgate.assessment.tiers import Band, RateSchedule
from headgate.errors import PolicyError, ValidationError
from headgate.ids import AccountNumber
from headgate.money import Money

HOLDER = AccountNumber(118)
DUE = date(2025, 12, 1)


def schedule(water_year: int = 2025) -> RateSchedule:
    return RateSchedule(
        water_year=water_year,
        per_share=Money.from_dollars("4.50"),
        bands=(Band(None, Money.from_dollars("2.00")),),
    )


def bill(water_year: int = 2025, delivered: str = "50", issued: date = date(2025, 11, 1)) -> Bill:
    return bill_account(
        account=HOLDER,
        water_year=water_year,
        issued_on=issued,
        schedule=schedule(water_year),
        shares=Decimal("20"),
        delivered_af=Decimal(delivered),
    )


def payment(amount: str, on: date = date(2025, 11, 20)) -> Payment:
    return Payment(account=HOLDER, received_on=on, amount=Money.from_dollars(amount))


def ledger(*payments: Payment, bills: tuple[Bill, ...] | None = None) -> AccountLedger:
    return AccountLedger(
        account=HOLDER, bills=bills if bills is not None else (bill(),), payments=payments
    )


def test_a_payment_of_nothing_is_not_a_payment() -> None:
    with pytest.raises(ValidationError, match="is not a payment"):
        Payment(HOLDER, date(2025, 11, 20), Money.zero())


def test_a_write_off_is_not_money() -> None:
    assert PaymentMethod.CHEQUE.is_money
    assert not PaymentMethod.WRITE_OFF.is_money


def test_the_balance_is_what_was_billed_less_what_was_paid() -> None:
    assert ledger().balance == bill().total
    assert ledger(payment("50.00")).balance == bill().total - Money.from_dollars("50.00")


def test_an_account_paid_in_full_is_clear() -> None:
    paid = ledger(payment("190.00"))
    assert paid.is_clear
    assert paid.balance == Money.zero()


def test_a_bill_for_another_account_is_refused() -> None:
    other = bill_account(
        account=AccountNumber(212),
        water_year=2025,
        issued_on=date(2025, 11, 1),
        schedule=schedule(),
        shares=Decimal("4"),
        delivered_af=Decimal("10"),
    )
    with pytest.raises(ValidationError, match="turned up on account"):
        AccountLedger(account=HOLDER, bills=(other,))


def test_a_payment_from_another_account_is_refused() -> None:
    stranger = Payment(AccountNumber(212), date(2025, 11, 20), Money.from_dollars("10.00"))
    with pytest.raises(ValidationError, match="turned up on account"):
        AccountLedger(account=HOLDER, bills=(bill(),), payments=(stranger,))
    with pytest.raises(PolicyError, match="cannot land on account"):
        ledger().with_payment(stranger)


def test_a_payment_can_be_added_to_the_ledger() -> None:
    added = ledger().with_payment(payment("90.00"))
    assert added.paid == Money.from_dollars("90.00")


def test_a_balance_can_be_asked_for_as_of_a_day() -> None:
    book = ledger(payment("90.00", date(2025, 12, 15)))
    assert book.balance_on(date(2025, 12, 1)) == bill().total
    assert book.balance_on(date(2025, 12, 31)) < bill().total


def test_money_lands_on_the_oldest_bill_first() -> None:
    two_years = (bill(2024, "40", date(2024, 11, 1)), bill(2025, "50"))
    book = ledger(payment("100.00"), bills=two_years)
    landed = book.apply()
    assert landed[0].water_year == 2024
    assert landed[0].amount == Money.from_dollars("100.00")


def test_a_payment_that_covers_the_first_bill_moves_to_the_next() -> None:
    two_years = (bill(2024, "40", date(2024, 11, 1)), bill(2025, "50"))
    book = ledger(payment("200.00"), bills=two_years)
    landed = book.apply()
    assert len(landed) == 2
    assert landed[1].water_year == 2025


def test_the_years_still_owing_are_listed() -> None:
    two_years = (bill(2024, "40", date(2024, 11, 1)), bill(2025, "50"))
    book = ledger(payment("170.00"), bills=two_years)
    assert 2025 in book.unpaid_years()


def test_nothing_is_late_before_the_due_date() -> None:
    assert ledger().days_late(DUE, date(2025, 11, 15)) == 0
    assert not ledger().is_delinquent(DUE, date(2025, 11, 15))


def test_an_account_paid_up_is_never_late() -> None:
    paid = ledger(payment("190.00"))
    assert paid.days_late(DUE, date(2026, 6, 1)) == 0
    assert not paid.is_delinquent(DUE, date(2026, 6, 1))


def test_the_grace_period_holds_the_penalty_off() -> None:
    assert ledger().penalty(DUE, date(2025, 12, 20)) == Money.zero()
    assert not ledger().is_delinquent(DUE, date(2025, 12, 20))


def test_past_the_grace_period_the_penalty_runs() -> None:
    charged = ledger().penalty(DUE, date(2026, 3, 1))
    assert charged.cents > 0
    assert ledger().is_delinquent(DUE, date(2026, 3, 1))


def test_the_penalty_grows_with_the_months() -> None:
    early = ledger().penalty(DUE, date(2026, 2, 1))
    late = ledger().penalty(DUE, date(2026, 6, 1))
    assert late > early


def test_a_bigger_balance_carries_a_bigger_penalty() -> None:
    small = ledger(payment("150.00")).penalty(DUE, date(2026, 6, 1))
    large = ledger().penalty(DUE, date(2026, 6, 1))
    assert large > small


def test_a_negative_penalty_rate_is_refused() -> None:
    with pytest.raises(ValidationError, match="may not be negative"):
        ledger().penalty(DUE, date(2026, 6, 1), monthly_rate=Decimal("-0.01"))


def test_the_water_goes_off_after_the_shutoff_period() -> None:
    assert not ledger().is_shut_off(DUE, date(2026, 1, 15))
    assert ledger().is_shut_off(DUE, date(2026, 4, 1))


def test_paying_up_puts_the_water_back_on() -> None:
    paid = ledger(payment("190.00", date(2026, 3, 1)))
    assert not paid.is_shut_off(DUE, date(2026, 4, 1))
