import sqlite3
from datetime import date
from decimal import Decimal

import pytest

from headgate.errors import ConflictError, NotFoundError
from headgate.ids import AccountNumber
from headgate.lease.agreement import Lease, LeaseSource, LeaseStatus
from headgate.model.account import Account, AccountStatus, ShareRegister
from headgate.money import Money
from headgate.store.repo_accounts import save_register
from headgate.store.repo_leases import (
    leases_for,
    load_book,
    load_lease,
    net_leased,
    offer,
    save_lease,
)

LESSOR = AccountNumber(118)
LESSEE = AccountNumber(212)


def stocked(book: sqlite3.Connection) -> None:
    save_register(
        book,
        ShareRegister(
            accounts=(
                Account(LESSOR, "Alma Peterson", date(1994, 3, 1), AccountStatus.ACTIVE),
                Account(LESSEE, "Ruth Larsen", date(1998, 5, 1), AccountStatus.ACTIVE),
            )
        ),
    )


def lease(number: str = "L-2025-3", volume: str = "80", year: int = 2025) -> Lease:
    return Lease(
        number=number,
        water_year=year,
        lessor=LESSOR,
        lessee=LESSEE,
        source=LeaseSource.ALLOTMENT,
        volume_af=Decimal(volume),
        price=Money.from_dollars("18.00"),
        offered_on=date(2025, 5, 1),
    )


def test_a_lease_comes_back_the_way_it_was_offered(book: sqlite3.Connection) -> None:
    stocked(book)
    offer(book, lease())
    assert load_lease(book, "L-2025-3") == lease()


def test_the_same_number_twice_is_a_conflict(book: sqlite3.Connection) -> None:
    stocked(book)
    offer(book, lease())
    with pytest.raises(ConflictError, match="already in the book"):
        offer(book, lease())


def test_a_lease_between_accounts_that_are_not_there_is_refused(
    book: sqlite3.Connection,
) -> None:
    with pytest.raises(sqlite3.IntegrityError):
        offer(book, lease())


def test_the_book_refuses_a_lease_to_itself(book: sqlite3.Connection) -> None:
    stocked(book)
    with pytest.raises(sqlite3.IntegrityError):
        book.execute(
            "INSERT INTO lease (number, water_year, lessor, lessee, source, volume_af,"
            " price_cents, offered_on, status)"
            " VALUES ('L-2025-9', 2025, 118, 118, 'allotment', '10', 1800, '2025-05-01',"
            " 'offered')"
        )


def test_approving_and_delivering_are_written_back(book: sqlite3.Connection) -> None:
    stocked(book)
    offer(book, lease())
    approved = load_lease(book, "L-2025-3").approve("board minute 2025-4")
    save_lease(book, approved.deliver(Decimal("30")))
    loaded = load_lease(book, "L-2025-3")
    assert loaded.status is LeaseStatus.APPROVED
    assert loaded.delivered_af == Decimal("30.0000")
    assert loaded.note == "board minute 2025-4"


def test_a_lease_that_is_not_there_is_reported_missing(book: sqlite3.Connection) -> None:
    with pytest.raises(NotFoundError, match="no lease"):
        load_lease(book, "L-2025-9")
    with pytest.raises(NotFoundError):
        save_lease(book, lease())


def test_the_book_comes_back_for_one_year(book: sqlite3.Connection) -> None:
    stocked(book)
    offer(book, lease("L-2025-3"))
    offer(book, lease("L-2024-1", year=2024))
    assert [item.number for item in load_book(book, 2025).leases] == ["L-2025-3"]


def test_the_leases_an_account_is_on_come_back(book: sqlite3.Connection) -> None:
    stocked(book)
    offer(book, lease("L-2025-3"))
    assert len(leases_for(book, LESSOR, 2025)) == 1
    assert len(leases_for(book, LESSEE, 2025)) == 1
    assert leases_for(book, LESSOR, 2024) == ()


def test_the_net_position_counts_only_approved_leases(book: sqlite3.Connection) -> None:
    stocked(book)
    offer(book, lease("L-2025-3"))
    assert net_leased(book, LESSOR, 2025) == Decimal("0")
    save_lease(book, load_lease(book, "L-2025-3").approve())
    assert net_leased(book, LESSOR, 2025) == Decimal("-80")
    assert net_leased(book, LESSEE, 2025) == Decimal("80")


def test_a_cancelled_lease_moves_nothing(book: sqlite3.Connection) -> None:
    stocked(book)
    offer(book, lease())
    approved = load_lease(book, "L-2025-3").approve()
    save_lease(book, approved.cancel("the lessee sold up"))
    assert net_leased(book, LESSOR, 2025) == Decimal("0")


def test_a_year_with_no_leases_reads_empty(book: sqlite3.Connection) -> None:
    assert load_book(book, 2025).leases == ()
