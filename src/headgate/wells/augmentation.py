"""The plan that keeps a well pumping in a call year.

A well that depletes the creek in a call year is out of priority and has to
stop, unless the owner puts the water back. The paper that lets him do that is
an augmentation plan: a list of replacement sources, what each can produce
month by month, and where in the stream it lands.

Three things have to line up and a plan that misses any of them is not a plan.

Time. Replacement in April does nothing for a depletion in August. The match is
made month by month and the surplus in one month does not carry into the next,
because the senior right that was short in August was short in August.

Place. Water put back below the calling right runs past it. A source has to
deliver at or above the point the depletion is felt, and one that does not is
worth nothing however much of it there is.

Legal availability. The same acre foot cannot be counted twice, so a source
already committed to another plan is not available to this one.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from enum import Enum

from ..errors import PolicyError, ValidationError
from ..units import round_volume
from .depletion import PumpingRecord, depletion_by_month


class SourceKind(Enum):
    """Where the replacement water comes from."""

    STORAGE_RELEASE = "storage_release"
    LEASE = "lease"
    RECHARGE_CREDIT = "recharge_credit"
    DRY_UP_CREDIT = "dry_up_credit"

    @property
    def is_a_credit(self) -> bool:
        """A credit is water that was never taken rather than water released."""

        return self in {SourceKind.RECHARGE_CREDIT, SourceKind.DRY_UP_CREDIT}


@dataclass(frozen=True, slots=True)
class ReplacementSource:
    """One source of replacement water, and where it lands."""

    name: str
    kind: SourceKind
    delivery_mile: Decimal
    monthly_af: dict[int, Decimal]
    committed_elsewhere: bool = False

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise ValidationError("a replacement source needs a name")
        for month, volume in self.monthly_af.items():
            if month < 1 or month > 12:
                raise ValidationError(f"{month} is not a month in source {self.name}")
            if volume < 0:
                raise ValidationError(f"source {self.name} offers a negative volume")

    @property
    def annual_af(self) -> Decimal:
        return round_volume(sum(self.monthly_af.values(), Decimal("0")))

    def available_in(self, month: int) -> Decimal:
        if self.committed_elsewhere:
            return Decimal("0")
        return self.monthly_af.get(month, Decimal("0"))

    def reaches(self, depletion_mile: Decimal) -> bool:
        """Whether this water lands where the depletion is felt, or above it."""

        return self.delivery_mile >= depletion_mile


@dataclass(frozen=True, slots=True)
class MonthMatch:
    """One month of the plan, owed against replaced."""

    month: int
    owed_af: Decimal
    replaced_af: Decimal

    @property
    def shortfall_af(self) -> Decimal:
        short = self.owed_af - self.replaced_af
        return round_volume(short) if short > 0 else Decimal("0")

    @property
    def surplus_af(self) -> Decimal:
        over = self.replaced_af - self.owed_af
        return round_volume(over) if over > 0 else Decimal("0")

    @property
    def is_covered(self) -> bool:
        return self.shortfall_af == 0


@dataclass(frozen=True, slots=True)
class AugmentationPlan:
    """A plan, the wells it covers and the sources it leans on."""

    name: str
    depletion_mile: Decimal
    sources: tuple[ReplacementSource, ...]

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise ValidationError("an augmentation plan needs a name")
        seen: set[str] = set()
        for source in self.sources:
            if source.name in seen:
                raise ValidationError(f"plan {self.name} lists source {source.name} twice")
            seen.add(source.name)

    @property
    def usable_sources(self) -> tuple[ReplacementSource, ...]:
        return tuple(
            source
            for source in self.sources
            if source.reaches(self.depletion_mile) and not source.committed_elsewhere
        )

    @property
    def out_of_place(self) -> tuple[ReplacementSource, ...]:
        return tuple(source for source in self.sources if not source.reaches(self.depletion_mile))

    def available_in(self, month: int) -> Decimal:
        return round_volume(
            sum((source.available_in(month) for source in self.usable_sources), Decimal("0"))
        )

    def match(self, records: list[PumpingRecord], through_month: int) -> tuple[MonthMatch, ...]:
        """Line the depletion up against the replacement, month by month."""

        owed = depletion_by_month(records, through_month)
        months = sorted(set(owed) | set(range(1, through_month + 1)))
        return tuple(
            MonthMatch(
                month=month,
                owed_af=owed.get(month, Decimal("0")),
                replaced_af=self.available_in(month),
            )
            for month in months
            if owed.get(month, Decimal("0")) > 0 or self.available_in(month) > 0
        )

    def shortfall(self, records: list[PumpingRecord], through_month: int) -> Decimal:
        return round_volume(
            sum((item.shortfall_af for item in self.match(records, through_month)), Decimal("0"))
        )

    def covers(self, records: list[PumpingRecord], through_month: int) -> bool:
        return all(item.is_covered for item in self.match(records, through_month))

    def first_short_month(self, records: list[PumpingRecord], through_month: int) -> int | None:
        for item in self.match(records, through_month):
            if not item.is_covered:
                return item.month
        return None


def require_cover(
    plan: AugmentationPlan, records: list[PumpingRecord], through_month: int
) -> AugmentationPlan:
    """Insist a plan covers its depletions, for a caller about to approve it."""

    short = plan.first_short_month(records, through_month)
    if short is not None:
        raise PolicyError(
            f"plan {plan.name} is short {plan.shortfall(records, through_month)} acre feet, "
            f"first in month {short}"
        )
    return plan
