from datetime import date
from decimal import Decimal

import pytest

from headgate.errors import NotFoundError, PolicyError, ValidationError
from headgate.ids import AccountNumber
from headgate.lease.agreement import (
    Lease,
    LeaseBook,
    LeaseSource,
    LeaseStatus,
    check_available,
)
from headgate.money import Money

LESSOR = AccountNumber(118)
LESSEE = AccountNumber(212)
OFFERED = date(2025, 5, 1)


def lease(number: str = "L-2025-3", volume: str = "80", **overrides: object) -> Lease:
    fields: dict[str, object] = {
        "number": number,
        "water_year": 2025,
        "lessor": LESSOR,
        "lessee": LESSEE,
        "source": LeaseSource.ALLOTMENT,
        "volume_af": Decimal(volume),
        "price": Money.from_dollars("18.00"),
        "offered_on": OFFERED,
    }
    fields.update(overrides)
    return Lease(**fields)  # type: ignore[arg-type]


def test_a_lease_needs_a_number_and_some_water() -> None:
    with pytest.raises(ValidationError, match="needs a number"):
        lease(number="  ")
    with pytest.raises(ValidationError, match="moves no water"):
        lease(volume="0")


def test_an_account_cannot_lease_to_itself() -> None:
    with pytest.raises(PolicyError, match="to itself"):
        lease(lessee=LESSOR)


def test_a_lease_is_worth_its_volume_at_its_price() -> None:
    assert lease().value == Money.from_dollars("1440.00")


def test_a_lease_runs_offered_then_approved() -> None:
    approved = lease().approve("board minute 2025-4")
    assert approved.status is LeaseStatus.APPROVED
    assert approved.status.can_deliver
    with pytest.raises(PolicyError, match="not offered"):
        approved.approve()


def test_an_offered_lease_delivers_nothing() -> None:
    with pytest.raises(PolicyError, match="cannot deliver water"):
        lease().deliver(Decimal("10"))


def test_delivering_draws_the_lease_down() -> None:
    running = lease().approve().deliver(Decimal("30"))
    assert running.delivered_af == Decimal("30")
    assert running.remaining_af == Decimal("50")
    assert running.is_started


def test_delivering_the_whole_lease_finishes_it() -> None:
    finished = lease().approve().deliver(Decimal("80"))
    assert finished.status is LeaseStatus.COMPLETED
    assert finished.remaining_af == Decimal("0")


def test_delivering_more_than_is_left_is_refused() -> None:
    running = lease().approve().deliver(Decimal("70"))
    with pytest.raises(PolicyError, match="acre feet left"):
        running.deliver(Decimal("20"))


def test_a_delivery_of_nothing_is_refused() -> None:
    with pytest.raises(ValidationError, match="some water"):
        lease().approve().deliver(Decimal("0"))


def test_a_lease_can_be_cancelled_before_it_starts() -> None:
    cancelled = lease().approve().cancel("the lessee sold up")
    assert cancelled.status is LeaseStatus.CANCELLED
    assert not cancelled.status.can_deliver


def test_a_lease_that_has_delivered_cannot_be_cancelled() -> None:
    running = lease().approve().deliver(Decimal("10"))
    with pytest.raises(PolicyError, match="already delivered"):
        running.cancel("too late")


def test_a_finished_lease_cannot_be_cancelled() -> None:
    finished = lease().approve().deliver(Decimal("80"))
    with pytest.raises(PolicyError, match="already delivered"):
        finished.cancel("too late")


def test_a_lease_that_ran_out_without_delivering_is_still_finished() -> None:
    finished = lease().approve().deliver(Decimal("80"))
    assert finished.status is LeaseStatus.COMPLETED
    assert not finished.status.can_deliver


def test_a_lease_carrying_more_delivery_than_water_is_refused() -> None:
    with pytest.raises(PolicyError, match="has delivered"):
        lease(delivered_af=Decimal("90"))


def test_stored_water_is_a_different_sort_of_lease() -> None:
    assert LeaseSource.STORAGE.is_stored_water
    assert not LeaseSource.ALLOTMENT.is_stored_water


def book(*leases: Lease) -> LeaseBook:
    return LeaseBook(water_year=2025, leases=leases)


def test_the_book_refuses_the_same_number_twice() -> None:
    with pytest.raises(ValidationError, match="appears twice"):
        book(lease(), lease())
    with pytest.raises(PolicyError, match="already in the book"):
        book(lease()).add(lease())


def test_the_book_refuses_a_lease_from_another_year() -> None:
    with pytest.raises(ValidationError, match="turned up in the"):
        book(lease(water_year=2024))


def test_a_lease_can_be_looked_up_and_replaced() -> None:
    written = book(lease())
    approved = written.lease("L-2025-3").approve()
    assert written.replace_lease(approved).lease("L-2025-3").status is LeaseStatus.APPROVED
    with pytest.raises(NotFoundError, match="no lease"):
        written.lease("L-2025-9")


def test_only_approved_leases_are_live() -> None:
    written = book(lease(), lease("L-2025-4").approve())
    assert [item.number for item in written.live] == ["L-2025-4"]


def test_water_leased_out_and_in_is_counted() -> None:
    written = book(
        lease("L-2025-3").approve(),
        lease("L-2025-4", "20", lessor=LESSEE, lessee=LESSOR).approve(),
    )
    assert written.leased_out(LESSOR) == Decimal("80")
    assert written.leased_in(LESSOR) == Decimal("20")
    assert written.net_for(LESSOR) == Decimal("-60")


def test_an_offered_lease_commits_nothing_yet() -> None:
    assert book(lease()).leased_out(LESSOR) == Decimal("0")


def test_a_lessor_cannot_offer_water_it_does_not_have() -> None:
    written = book(lease("L-2025-3").approve())
    with pytest.raises(PolicyError, match="uncommitted"):
        check_available(written, LESSOR, Decimal("100"), Decimal("40"))


def test_what_is_left_after_a_lease_is_reported() -> None:
    written = book(lease("L-2025-3").approve())
    assert check_available(written, LESSOR, Decimal("200"), Decimal("40")) == Decimal("80")


def test_a_lease_of_nothing_is_refused() -> None:
    with pytest.raises(ValidationError, match="not a lease"):
        check_available(book(), LESSOR, Decimal("200"), Decimal("0"))
