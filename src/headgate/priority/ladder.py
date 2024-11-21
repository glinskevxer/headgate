"""Handing out a supply down the priority ladder.

The rule is not proportional and it is not fair. The most senior right takes
its whole decreed rate before the next one takes anything, and the right that
runs out gets whatever is left rather than a share of it. Everything below that
gets nothing at all.

Storage is filled after direct flow, whatever the paper priority says. A
reservoir that fills while an irrigator downstream is short is the fastest way
to get a district sued, and the practice in this basin has been to pass the
direct flow first for a century.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from ..errors import ValidationError
from ..ids import DecreeNumber
from ..model.right import RightKind, WaterRight, order_by_priority
from ..units import round_rate, total_rate


@dataclass(frozen=True, slots=True)
class Allocation:
    """What one right gets out of a supply."""

    right: WaterRight
    allocated_cfs: Decimal
    shorted_cfs: Decimal

    @property
    def is_whole(self) -> bool:
        return self.shorted_cfs == 0

    @property
    def is_dry(self) -> bool:
        return self.allocated_cfs == 0


@dataclass(frozen=True, slots=True)
class Distribution:
    """The whole ladder, worked from the top down against one supply."""

    supply_cfs: Decimal
    allocations: tuple[Allocation, ...]

    @property
    def total_allocated_cfs(self) -> Decimal:
        return total_rate(item.allocated_cfs for item in self.allocations)

    @property
    def unallocated_cfs(self) -> Decimal:
        return round_rate(self.supply_cfs - self.total_allocated_cfs)

    @property
    def is_short(self) -> bool:
        return any(not item.is_whole for item in self.allocations)

    @property
    def first_shorted(self) -> Allocation | None:
        for item in self.allocations:
            if not item.is_whole:
                return item
        return None

    @property
    def dry_rights(self) -> tuple[Allocation, ...]:
        return tuple(item for item in self.allocations if item.is_dry)

    def for_decree(self, decree: DecreeNumber) -> Allocation:
        for item in self.allocations:
            if item.right.decree == decree:
                return item
        raise ValidationError(f"decree {decree} was not in this distribution")


def _demand_of(right: WaterRight) -> Decimal:
    return right.rate_or_zero()


def distribute(
    rights: list[WaterRight], supply_cfs: Decimal, fill_storage: bool = True
) -> Distribution:
    """Work a supply down the ladder, most senior first."""

    if supply_cfs < 0:
        raise ValidationError("a stream cannot carry a negative supply")
    active = [right for right in rights if right.is_active]
    direct = order_by_priority([r for r in active if r.kind is not RightKind.STORAGE])
    storage = order_by_priority([r for r in active if r.kind is RightKind.STORAGE])
    ordered = direct + (storage if fill_storage else [])
    remaining = supply_cfs
    allocations: list[Allocation] = []
    for right in ordered:
        wanted = _demand_of(right)
        given = wanted if remaining >= wanted else remaining
        allocations.append(
            Allocation(
                right=right,
                allocated_cfs=round_rate(given),
                shorted_cfs=round_rate(wanted - given),
            )
        )
        remaining = remaining - given
    return Distribution(supply_cfs=round_rate(supply_cfs), allocations=tuple(allocations))


def supply_to_satisfy(rights: list[WaterRight], decree: DecreeNumber) -> Decimal:
    """How much has to be in the stream before a right sees its full rate."""

    active = [right for right in rights if right.is_active]
    direct = order_by_priority([r for r in active if r.kind is not RightKind.STORAGE])
    storage = order_by_priority([r for r in active if r.kind is RightKind.STORAGE])
    needed = Decimal("0")
    for right in direct + storage:
        needed += _demand_of(right)
        if right.decree == decree:
            return round_rate(needed)
    raise ValidationError(f"decree {decree} is not on this ladder")


def shortfall_of(distribution: Distribution, decree: DecreeNumber) -> Decimal:
    """What a right is short, which is what a call would be asking for."""

    return distribution.for_decree(decree).shorted_cfs
