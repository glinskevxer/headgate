import sqlite3
from datetime import date
from decimal import Decimal

import pytest

from headgate.errors import NotFoundError
from headgate.ids import AccountNumber, DecreeNumber
from headgate.model.account import Account, AccountStatus, ShareRegister
from headgate.model.reservoir import PoolState, Reservoir
from headgate.model.right import Priority, RightKind, WaterRight
from headgate.storage.account import allocate
from headgate.store.repo_accounts import save_register
from headgate.store.repo_rights import save_right
from headgate.store.repo_storage import (
    load_pool,
    load_reservoir,
    load_storage_book,
    save_pool,
    save_reservoir,
    save_storage_book,
    stored_for,
)

DECREE = DecreeNumber("CDA-1920-40")
FIRST = AccountNumber(118)
SECOND = AccountNumber(212)


def reservoir() -> Reservoir:
    return Reservoir(
        name="Ephraim Reservoir",
        decree=DECREE,
        capacity_af=Decimal("4000"),
        dead_pool_af=Decimal("300"),
    )


def stocked(book: sqlite3.Connection) -> None:
    save_right(
        book,
        WaterRight(
            decree=DECREE,
            owner="Sanpete Ditch Company",
            kind=RightKind.STORAGE,
            priority=Priority(date(1911, 5, 1), 1920, 40),
            diversion_mile=Decimal("31"),
            volume_af=Decimal("4000"),
        ),
    )
    save_register(
        book,
        ShareRegister(
            accounts=(
                Account(FIRST, "Holder 118", date(1994, 3, 1), AccountStatus.ACTIVE),
                Account(SECOND, "Holder 212", date(1998, 5, 1), AccountStatus.ACTIVE),
            )
        ),
    )
    save_reservoir(book, reservoir())


def test_a_reservoir_comes_back_the_way_it_went_in(book: sqlite3.Connection) -> None:
    stocked(book)
    assert load_reservoir(book, "Ephraim Reservoir") == reservoir()


def test_a_reservoir_that_is_not_there_is_reported_missing(book: sqlite3.Connection) -> None:
    with pytest.raises(NotFoundError, match="no reservoir"):
        load_reservoir(book, "Ephraim Reservoir")


def test_a_reservoir_needs_a_decree_behind_it(book: sqlite3.Connection) -> None:
    with pytest.raises(sqlite3.IntegrityError):
        save_reservoir(book, reservoir())


def test_a_fill_season_survives_the_trip(book: sqlite3.Connection) -> None:
    stocked(book)
    early = Reservoir(
        name="Ephraim Reservoir",
        decree=DECREE,
        capacity_af=Decimal("4000"),
        dead_pool_af=Decimal("300"),
        fill_opens=(10, 15),
        fill_closes=(6, 15),
    )
    save_reservoir(book, early)
    assert load_reservoir(book, "Ephraim Reservoir").fill_opens == (10, 15)


def test_a_pool_comes_back_with_what_it_did(book: sqlite3.Connection) -> None:
    stocked(book)
    pool = PoolState(reservoir=reservoir(), water_year=2025, contents_af=Decimal("1000"))
    filled = pool.fill(Decimal("500"), date(2025, 4, 1)).release(Decimal("200"))
    save_pool(book, filled)
    loaded = load_pool(book, "Ephraim Reservoir", 2025)
    assert loaded.contents_af == filled.contents_af
    assert loaded.released_af == Decimal("200")
    assert loaded.fill_finished


def test_saving_a_pool_twice_updates_it(book: sqlite3.Connection) -> None:
    stocked(book)
    pool = PoolState(reservoir=reservoir(), water_year=2025, contents_af=Decimal("1000"))
    save_pool(book, pool)
    save_pool(book, pool.fill(Decimal("400"), date(2025, 4, 1)))
    assert load_pool(book, "Ephraim Reservoir", 2025).contents_af == Decimal("1400")


def test_a_year_with_no_pool_is_reported_missing(book: sqlite3.Connection) -> None:
    stocked(book)
    with pytest.raises(NotFoundError, match="no pool"):
        load_pool(book, "Ephraim Reservoir", 2025)


def test_the_storage_book_comes_back_account_by_account(book: sqlite3.Connection) -> None:
    stocked(book)
    allocated = allocate(2025, Decimal("1200"), {FIRST: Decimal("20"), SECOND: Decimal("10")})
    save_storage_book(book, "Ephraim Reservoir", allocated)
    loaded = load_storage_book(book, "Ephraim Reservoir", 2025)
    assert loaded == allocated
    assert loaded.balance_of(FIRST) == Decimal("800")


def test_saving_the_storage_book_again_replaces_it(book: sqlite3.Connection) -> None:
    stocked(book)
    allocated = allocate(2025, Decimal("1200"), {FIRST: Decimal("20"), SECOND: Decimal("10")})
    save_storage_book(book, "Ephraim Reservoir", allocated)
    save_storage_book(book, "Ephraim Reservoir", allocated.release_to(FIRST, Decimal("300")))
    assert load_storage_book(book, "Ephraim Reservoir", 2025).balance_of(FIRST) == Decimal("500")


def test_a_year_with_no_storage_book_is_reported_missing(book: sqlite3.Connection) -> None:
    stocked(book)
    with pytest.raises(NotFoundError, match="no storage book"):
        load_storage_book(book, "Ephraim Reservoir", 2025)


def test_an_account_balance_adds_up_across_reservoirs(book: sqlite3.Connection) -> None:
    stocked(book)
    allocated = allocate(2025, Decimal("1200"), {FIRST: Decimal("20"), SECOND: Decimal("10")})
    save_storage_book(book, "Ephraim Reservoir", allocated)
    assert stored_for(book, FIRST, 2025) == Decimal("800")
    assert stored_for(book, FIRST, 2024) == Decimal("0")
