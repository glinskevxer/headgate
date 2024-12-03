import sqlite3
from datetime import date
from decimal import Decimal

import pytest

from headgate.assessment.billing import bill_account
from headgate.assessment.payment import Payment, PaymentMethod
from headgate.assessment.tiers import Band, RateSchedule
from headgate.errors import NotFoundError
from headgate.ids import AccountNumber
from headgate.model.account import Account, AccountStatus, ShareRegister
from headgate.money import Money
from headgate.store.repo_accounts import save_register
from headgate.store.repo_bills import save_bill
from headgate.store.repo_payments import (
    account_ledger,
    load_payment,
    next_payment_number,
    payments_for,
    take_payment,
    taken_between,
    taken_total,
)

HOLDER = AccountNumber(118)
OTHER = AccountNumber(212)


def stocked(book: sqlite3.Connection) -> None:
    save_register(
        book,
        ShareRegister(
            accounts=(
                Account(HOLDER, "Alma Peterson", date(1994, 3, 1), AccountStatus.ACTIVE),
                Account(OTHER, "Ruth Larsen", date(1998, 5, 1), AccountStatus.ACTIVE),
            )
        ),
    )


def schedule() -> RateSchedule:
    return RateSchedule(
        water_year=2025,
        per_share=Money.from_dollars("4.50"),
        bands=(Band(None, Money.from_dollars("2.00")),),
    )


def payment(amount: str, on: str = "2025-11-20", account: AccountNumber = HOLDER) -> Payment:
    return Payment(
        account=account,
        received_on=date.fromisoformat(on),
        amount=Money.from_dollars(amount),
        reference="cheque 1184",
    )


def test_a_payment_comes_back_the_way_it_went_in(book: sqlite3.Connection) -> None:
    stocked(book)
    number = take_payment(book, payment("90.00"))
    assert load_payment(book, number) == payment("90.00")


def test_payments_are_numbered_in_order(book: sqlite3.Connection) -> None:
    stocked(book)
    assert next_payment_number(book) == 1
    assert take_payment(book, payment("90.00")) == 1
    assert take_payment(book, payment("40.00")) == 2


def test_a_payment_that_is_not_there_is_reported_missing(book: sqlite3.Connection) -> None:
    with pytest.raises(NotFoundError, match="no payment"):
        load_payment(book, 9)


def test_a_payment_from_an_account_that_is_not_there_is_refused(
    book: sqlite3.Connection,
) -> None:
    with pytest.raises(sqlite3.IntegrityError):
        take_payment(book, payment("90.00"))


def test_the_book_refuses_a_payment_of_nothing(book: sqlite3.Connection) -> None:
    stocked(book)
    with pytest.raises(sqlite3.IntegrityError):
        book.execute(
            "INSERT INTO payment (payment_id, account_number, received_on, amount_cents,"
            " method) VALUES (1, 118, '2025-11-20', 0, 'cheque')"
        )


def test_payments_for_an_account_come_back_oldest_first(book: sqlite3.Connection) -> None:
    stocked(book)
    take_payment(book, payment("40.00", "2025-12-05"))
    take_payment(book, payment("90.00", "2025-11-20"))
    take_payment(book, payment("10.00", account=OTHER))
    found = payments_for(book, HOLDER)
    assert [item.amount.cents for item in found] == [9000, 4000]


def test_payments_can_be_pulled_out_by_date(book: sqlite3.Connection) -> None:
    stocked(book)
    take_payment(book, payment("40.00", "2025-12-05"))
    take_payment(book, payment("90.00", "2025-11-20"))
    found = taken_between(book, date(2025, 12, 1), date(2026, 1, 1))
    assert len(found) == 1
    assert taken_total(book, date(2025, 12, 1), date(2026, 1, 1)) == Money.from_dollars("40.00")


def test_the_ledger_puts_the_bills_and_the_payments_together(
    book: sqlite3.Connection,
) -> None:
    stocked(book)
    save_bill(
        book,
        bill_account(
            account=HOLDER,
            water_year=2025,
            issued_on=date(2025, 11, 1),
            schedule=schedule(),
            shares=Decimal("20"),
            delivered_af=Decimal("50"),
        ),
    )
    take_payment(book, payment("90.00"))
    ledger = account_ledger(book, HOLDER)
    assert ledger.billed == Money.from_dollars("190.00")
    assert ledger.paid == Money.from_dollars("90.00")
    assert ledger.balance == Money.from_dollars("100.00")


def test_an_account_with_nothing_against_it_reads_clear(book: sqlite3.Connection) -> None:
    stocked(book)
    ledger = account_ledger(book, HOLDER)
    assert ledger.is_clear
    assert ledger.balance == Money.zero()


def test_a_write_off_lands_the_same_way_as_a_cheque(book: sqlite3.Connection) -> None:
    stocked(book)
    written = Payment(
        account=HOLDER,
        received_on=date(2026, 1, 15),
        amount=Money.from_dollars("25.00"),
        method=PaymentMethod.WRITE_OFF,
        reference="board minute 2026-1",
    )
    number = take_payment(book, written)
    assert load_payment(book, number).method is PaymentMethod.WRITE_OFF
