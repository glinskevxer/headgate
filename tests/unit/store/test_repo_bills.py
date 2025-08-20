import sqlite3
from datetime import date
from decimal import Decimal

import pytest

from headgate.assessment.billing import Bill, BillRun, bill_account
from headgate.assessment.repost import reverse
from headgate.assessment.tiers import Band, RateSchedule
from headgate.errors import NotFoundError, PolicyError
from headgate.ids import AccountNumber
from headgate.model.account import Account, AccountStatus, ShareRegister
from headgate.money import Money
from headgate.store.repo_accounts import save_register
from headgate.store.repo_bills import (
    balance_for,
    bills_for_account,
    issued_on,
    load_bill,
    load_run,
    next_bill_number,
    save_bill,
    save_run,
)

ISSUED = date(2025, 11, 1)
HOLDER = AccountNumber(118)
OTHER = AccountNumber(212)


def stocked(book: sqlite3.Connection) -> None:
    save_register(
        book,
        ShareRegister(
            accounts=(
                Account(HOLDER, "Holder 118", date(1994, 3, 1), AccountStatus.ACTIVE),
                Account(OTHER, "Holder 212", date(1998, 5, 1), AccountStatus.ACTIVE),
            )
        ),
    )


def schedule() -> RateSchedule:
    return RateSchedule(
        water_year=2025,
        per_share=Money.from_dollars("4.50"),
        bands=(
            Band(Decimal("50"), Money.from_dollars("2.00")),
            Band(None, Money.from_dollars("3.50")),
        ),
    )


def bill(account: AccountNumber = HOLDER, delivered: str = "60") -> Bill:
    return bill_account(
        account=account,
        water_year=2025,
        issued_on=ISSUED,
        schedule=schedule(),
        shares=Decimal("20"),
        delivered_af=Decimal(delivered),
    )


def test_a_bill_comes_back_with_its_lines(book: sqlite3.Connection) -> None:
    stocked(book)
    number = save_bill(book, bill())
    loaded = load_bill(book, number)
    assert loaded == bill()
    assert len(loaded.lines) == 2


def test_bills_are_numbered_in_the_order_they_are_written(book: sqlite3.Connection) -> None:
    stocked(book)
    assert next_bill_number(book) == 1
    assert save_bill(book, bill()) == 1
    assert save_bill(book, bill(OTHER)) == 2


def test_a_bill_with_no_lines_is_refused(book: sqlite3.Connection) -> None:
    stocked(book)
    empty = Bill(account=HOLDER, water_year=2025, issued_on=ISSUED, lines=())
    with pytest.raises(PolicyError, match="no lines on it"):
        save_bill(book, empty)


def test_a_bill_for_an_account_that_is_not_there_is_refused(book: sqlite3.Connection) -> None:
    with pytest.raises(sqlite3.IntegrityError):
        save_bill(book, bill())


def test_a_bill_that_is_not_there_is_reported_missing(book: sqlite3.Connection) -> None:
    with pytest.raises(NotFoundError, match="no bill"):
        load_bill(book, 9)


def test_a_whole_run_is_written_and_read_back(book: sqlite3.Connection) -> None:
    stocked(book)
    run = BillRun(water_year=2025, issued_on=ISSUED, bills=(bill(), bill(OTHER, "20")))
    assert save_run(book, run) == (1, 2)
    loaded = load_run(book, 2025)
    assert loaded.accounts == (HOLDER, OTHER)
    assert loaded.total == run.total


def test_a_year_with_no_run_is_reported_missing(book: sqlite3.Connection) -> None:
    with pytest.raises(NotFoundError, match="no bill run"):
        load_run(book, 2025)


def test_only_the_bill_that_stands_is_in_the_run(book: sqlite3.Connection) -> None:
    stocked(book)
    number = save_bill(book, bill())
    save_bill(book, reverse(bill(), date(2026, 1, 15), "weir read high"), reverses=number)
    save_bill(book, bill(delivered="40"))
    loaded = load_run(book, 2025)
    assert len(loaded.bills) == 1
    assert loaded.bills[0].total == bill(delivered="40").total


def test_a_season_whose_only_bill_was_reversed_has_no_run(
    book: sqlite3.Connection,
) -> None:
    stocked(book)
    number = save_bill(book, bill())
    save_bill(book, reverse(bill(), date(2026, 1, 15), "weir read high"), reverses=number)
    with pytest.raises(NotFoundError, match="no bill run"):
        load_run(book, 2025)


def test_an_account_history_carries_every_bill(book: sqlite3.Connection) -> None:
    stocked(book)
    number = save_bill(book, bill())
    save_bill(book, reverse(bill(), date(2026, 1, 15), "weir read high"), reverses=number)
    assert len(bills_for_account(book, HOLDER)) == 2


def test_a_reversal_nets_the_balance_back_to_nothing(book: sqlite3.Connection) -> None:
    stocked(book)
    number = save_bill(book, bill())
    assert balance_for(book, HOLDER) == bill().total
    save_bill(book, reverse(bill(), date(2026, 1, 15), "weir read high"), reverses=number)
    assert balance_for(book, HOLDER) == Money.zero()


def test_a_balance_can_be_asked_for_one_year(book: sqlite3.Connection) -> None:
    stocked(book)
    save_bill(book, bill())
    assert balance_for(book, HOLDER, 2025) == bill().total
    assert balance_for(book, HOLDER, 2024) == Money.zero()


def test_the_day_a_year_was_billed_comes_back(book: sqlite3.Connection) -> None:
    stocked(book)
    save_bill(book, bill())
    assert issued_on(book, 2025) == ISSUED
    assert issued_on(book, 2024) is None
