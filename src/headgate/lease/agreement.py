"""Leasing water for a season, which is how a district moves water in a hurry.

A transfer moves a right for good and takes a year. A lease moves this year's
water between two shareholders and takes an afternoon, because nothing about
the decree changes: the water still comes off the same right at the same
priority, and only the account it is delivered to is different.

That is also why a lease is hemmed in. It runs for one water year and dies. It
cannot move more than the lessor actually has this year. And the moment a drop
of it has been delivered it cannot be cancelled, because the water is on the
ground and somebody has to be billed for it.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import date
from decimal import Decimal
from enum import Enum

from ..errors import NotFoundError, PolicyError, ValidationError
from ..ids import AccountNumber
from ..money import Money
from ..units import round_volume


class LeaseSource(Enum):
    """What the lessor is leasing out."""

    ALLOTMENT = "allotment"
    STORAGE = "storage"
    SHARES = "shares"

    @property
    def is_stored_water(self) -> bool:
        return self is LeaseSource.STORAGE


class LeaseStatus(Enum):
    """Where the lease stands."""

    OFFERED = "offered"
    APPROVED = "approved"
    CANCELLED = "cancelled"
    COMPLETED = "completed"

    @property
    def can_deliver(self) -> bool:
        return self is LeaseStatus.APPROVED


@dataclass(frozen=True, slots=True)
class Lease:
    """One season's water, moved from one account to another."""

    number: str
    water_year: int
    lessor: AccountNumber
    lessee: AccountNumber
    source: LeaseSource
    volume_af: Decimal
    price: Money
    offered_on: date
    status: LeaseStatus = LeaseStatus.OFFERED
    delivered_af: Decimal = Decimal("0")
    note: str = ""

    def __post_init__(self) -> None:
        if not self.number.strip():
            raise ValidationError("a lease needs a number")
        if self.lessor == self.lessee:
            raise PolicyError(f"lease {self.number} moves water from an account to itself")
        if self.volume_af <= 0:
            raise ValidationError(f"lease {self.number} moves no water")
        if self.delivered_af < 0:
            raise ValidationError(f"lease {self.number} has a negative delivery on it")
        if self.delivered_af > self.volume_af:
            raise PolicyError(
                f"lease {self.number} has delivered {self.delivered_af} of "
                f"{self.volume_af} acre feet"
            )
        if self.price.cents < 0:
            raise ValidationError(f"lease {self.number} is priced below nothing")

    @property
    def remaining_af(self) -> Decimal:
        return round_volume(self.volume_af - self.delivered_af)

    @property
    def value(self) -> Money:
        return self.price.times(self.volume_af)

    @property
    def is_started(self) -> bool:
        return self.delivered_af > 0

    def approve(self, note: str = "") -> Lease:
        if self.status is not LeaseStatus.OFFERED:
            raise PolicyError(f"lease {self.number} is {self.status.value}, not offered")
        return replace(self, status=LeaseStatus.APPROVED, note=note)

    def cancel(self, note: str) -> Lease:
        if self.is_started:
            raise PolicyError(
                f"lease {self.number} has already delivered {self.delivered_af} acre feet"
            )
        if self.status is LeaseStatus.COMPLETED:
            raise PolicyError(f"lease {self.number} is finished")
        return replace(self, status=LeaseStatus.CANCELLED, note=note)

    def deliver(self, volume_af: Decimal) -> Lease:
        """Post water against the lease, which finishes it when it runs out."""

        if volume_af <= 0:
            raise ValidationError("a delivery against a lease has to be some water")
        if not self.status.can_deliver:
            raise PolicyError(
                f"lease {self.number} is {self.status.value} and cannot deliver water"
            )
        if volume_af > self.remaining_af:
            raise PolicyError(
                f"lease {self.number} has {self.remaining_af} acre feet left and was asked "
                f"for {volume_af}"
            )
        delivered = round_volume(self.delivered_af + volume_af)
        status = LeaseStatus.COMPLETED if delivered >= self.volume_af else self.status
        return replace(self, delivered_af=delivered, status=status)


@dataclass(frozen=True, slots=True)
class LeaseBook:
    """Every lease written for one water year."""

    water_year: int
    leases: tuple[Lease, ...] = ()

    def __post_init__(self) -> None:
        seen: set[str] = set()
        for lease in self.leases:
            if lease.number in seen:
                raise ValidationError(f"lease {lease.number} appears twice")
            if lease.water_year != self.water_year:
                raise ValidationError(
                    f"a {lease.water_year} lease turned up in the {self.water_year} book"
                )
            seen.add(lease.number)

    def lease(self, number: str) -> Lease:
        for item in self.leases:
            if item.number == number:
                return item
        raise NotFoundError("lease", number)

    def add(self, lease: Lease) -> LeaseBook:
        if any(item.number == lease.number for item in self.leases):
            raise PolicyError(f"lease {lease.number} is already in the book")
        return replace(self, leases=(*self.leases, lease))

    def replace_lease(self, lease: Lease) -> LeaseBook:
        self.lease(lease.number)
        return replace(
            self,
            leases=tuple(lease if item.number == lease.number else item for item in self.leases),
        )

    @property
    def live(self) -> tuple[Lease, ...]:
        return tuple(item for item in self.leases if item.status.can_deliver)

    def leased_out(self, account: AccountNumber) -> Decimal:
        """What an account has committed away and cannot use itself."""

        return round_volume(
            sum(
                (
                    item.volume_af
                    for item in self.leases
                    if item.lessor == account
                    and item.status in {LeaseStatus.APPROVED, LeaseStatus.COMPLETED}
                ),
                Decimal("0"),
            )
        )

    def leased_in(self, account: AccountNumber) -> Decimal:
        return round_volume(
            sum(
                (
                    item.volume_af
                    for item in self.leases
                    if item.lessee == account
                    and item.status in {LeaseStatus.APPROVED, LeaseStatus.COMPLETED}
                ),
                Decimal("0"),
            )
        )

    def net_for(self, account: AccountNumber) -> Decimal:
        return round_volume(self.leased_in(account) - self.leased_out(account))


def check_available(
    book: LeaseBook, lessor: AccountNumber, holding_af: Decimal, wanted_af: Decimal
) -> Decimal:
    """Refuse a lease of water the lessor does not have this year."""

    if wanted_af <= 0:
        raise ValidationError("a lease of no water is not a lease")
    spare = holding_af - book.leased_out(lessor)
    if wanted_af > spare:
        raise PolicyError(
            f"account {lessor} has {round_volume(spare)} acre feet uncommitted and offered "
            f"{wanted_af}"
        )
    return round_volume(spare - wanted_af)
