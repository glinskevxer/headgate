import sqlite3
from datetime import date
from decimal import Decimal

import pytest

from headgate.duty.allotment import allot
from headgate.errors import ConflictError, NotFoundError
from headgate.ids import AccountNumber
from headgate.model.account import Account, AccountStatus, ShareRegister
from headgate.store.repo_accounts import save_register
from headgate.store.repo_allotment import (
    allotment_on,
    current_allotment,
    load_ledger,
    revisions,
    save_ledger,
    set_allotment,
    used_by,
)

FIRST = AccountNumber(118)
SECOND = AccountNumber(212)


def stocked(book: sqlite3.Connection) -> None:
    save_register(
        book,
        ShareRegister(
            accounts=(
                Account(FIRST, "Alma Peterson", date(1994, 3, 1), AccountStatus.ACTIVE),
                Account(SECOND, "Ruth Larsen", date(1998, 5, 1), AccountStatus.ACTIVE),
            )
        ),
    )


def ledger(available: str = "600"):  # type: ignore[no-untyped-def]
    return allot(
        2025,
        Decimal(available),
        {FIRST: Decimal("20"), SECOND: Decimal("10")},
        date(2025, 4, 1),
        "April forecast",
    )


def test_an_allotment_comes_back_the_way_it_went_in(book: sqlite3.Connection) -> None:
    stocked(book)
    set_allotment(book, ledger().allotment)
    assert current_allotment(book, 2025) == ledger().allotment


def test_the_same_revision_twice_is_a_conflict(book: sqlite3.Connection) -> None:
    stocked(book)
    set_allotment(book, ledger().allotment)
    with pytest.raises(ConflictError, match="already written"):
        set_allotment(book, ledger().allotment)


def test_a_year_with_no_allotment_is_reported_missing(book: sqlite3.Connection) -> None:
    with pytest.raises(NotFoundError, match="no allotment"):
        current_allotment(book, 2025)


def test_the_latest_revision_is_the_one_that_stands(book: sqlite3.Connection) -> None:
    stocked(book)
    first = ledger().allotment
    set_allotment(book, first)
    cut = first.revise(Decimal("12"), date(2025, 8, 1), "creek quit")
    set_allotment(book, cut)
    assert current_allotment(book, 2025).af_per_share == Decimal("12")
    assert len(revisions(book, 2025)) == 2


def test_the_revision_that_stood_on_a_day_comes_back(book: sqlite3.Connection) -> None:
    stocked(book)
    first = ledger().allotment
    set_allotment(book, first)
    set_allotment(book, first.revise(Decimal("12"), date(2025, 8, 1), "creek quit"))
    assert allotment_on(book, 2025, date(2025, 6, 1)).af_per_share == Decimal("20")
    assert allotment_on(book, 2025, date(2025, 9, 1)).af_per_share == Decimal("12")


def test_a_day_before_the_first_revision_has_no_allotment(book: sqlite3.Connection) -> None:
    stocked(book)
    set_allotment(book, ledger().allotment)
    with pytest.raises(NotFoundError, match="no allotment"):
        allotment_on(book, 2025, date(2025, 3, 1))


def test_the_ledger_comes_back_account_by_account(book: sqlite3.Connection) -> None:
    stocked(book)
    set_allotment(book, ledger().allotment)
    save_ledger(book, ledger())
    loaded = load_ledger(book, 2025)
    assert loaded.allowed_af(FIRST) == Decimal("400")
    assert loaded.remaining_af(FIRST) == Decimal("400")


def test_using_water_is_written_back(book: sqlite3.Connection) -> None:
    stocked(book)
    set_allotment(book, ledger().allotment)
    save_ledger(book, ledger().take(FIRST, Decimal("150")))
    assert used_by(book, FIRST, 2025) == Decimal("150.0000")
    assert load_ledger(book, 2025).remaining_af(FIRST) == Decimal("250")


def test_an_account_not_on_the_ledger_is_reported_missing(book: sqlite3.Connection) -> None:
    stocked(book)
    set_allotment(book, ledger().allotment)
    with pytest.raises(NotFoundError, match="no allotment account"):
        used_by(book, AccountNumber(999), 2025)


def test_a_cut_allotment_reads_against_the_same_use(book: sqlite3.Connection) -> None:
    stocked(book)
    first = ledger().allotment
    set_allotment(book, first)
    save_ledger(book, ledger().take(FIRST, Decimal("380")))
    set_allotment(book, first.revise(Decimal("12"), date(2025, 8, 1), "creek quit"))
    loaded = load_ledger(book, 2025)
    assert loaded.is_over(FIRST)
    assert loaded.over_by(FIRST) == Decimal("140")
