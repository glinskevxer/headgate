"""Decreed water rights and what makes one senior to another.

Seniority is the appropriation date, not the date the court got around to
writing it down. Two rights appropriated the same day are separated by the
adjudication that confirmed them and then by their sequence in it, which is how
the decree book itself breaks the tie.

A direct flow right is a rate. A storage right is a volume, filled once a year.
Nothing in this module knows about a call or a curtailment; it only knows the
order they will be applied in.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from enum import Enum

from ..errors import ValidationError
from ..ids import DecreeNumber, DitchCode


class RightKind(Enum):
    """What the decree entitles the owner to take."""

    DIRECT_FLOW = "direct_flow"
    STORAGE = "storage"
    EXCHANGE = "exchange"


class RightStatus(Enum):
    """Where the right stands with the court today."""

    DECREED = "decreed"
    CONDITIONAL = "conditional"
    ABANDONED = "abandoned"


@dataclass(frozen=True, slots=True, order=True)
class Priority:
    """The place a right takes in the ladder, most senior first."""

    appropriation_date: date
    adjudication_year: int
    sequence: int

    def __post_init__(self) -> None:
        if self.sequence < 1:
            raise ValidationError(f"sequence {self.sequence} is not a place in the decree book")
        if self.adjudication_year < self.appropriation_date.year:
            raise ValidationError(
                f"an adjudication in {self.adjudication_year} cannot confirm an appropriation "
                f"from {self.appropriation_date.year}"
            )

    def is_senior_to(self, other: Priority) -> bool:
        return self < other

    def describe(self) -> str:
        return f"{self.appropriation_date.isoformat()} no {self.sequence}"


@dataclass(frozen=True, slots=True)
class WaterRight:
    """One decreed right, on one point of diversion."""

    decree: DecreeNumber
    owner: str
    kind: RightKind
    priority: Priority
    diversion_mile: Decimal
    rate_cfs: Decimal | None = None
    volume_af: Decimal | None = None
    ditch: DitchCode | None = None
    status: RightStatus = RightStatus.DECREED

    def __post_init__(self) -> None:
        if self.decree.adjudication_year != self.priority.adjudication_year:
            raise ValidationError(
                f"decree {self.decree} is numbered for {self.decree.adjudication_year} "
                f"and its priority says {self.priority.adjudication_year}"
            )
        if self.kind is RightKind.STORAGE:
            if self.volume_af is None or self.volume_af <= 0:
                raise ValidationError(f"storage right {self.decree} decrees no volume")
        elif self.rate_cfs is None or self.rate_cfs <= 0:
            raise ValidationError(f"{self.kind.value} right {self.decree} decrees no rate")
        if self.rate_cfs is not None and self.rate_cfs <= 0:
            raise ValidationError(f"right {self.decree} decrees a rate of {self.rate_cfs}")
        if self.volume_af is not None and self.volume_af <= 0:
            raise ValidationError(f"right {self.decree} decrees a volume of {self.volume_af}")

    @property
    def is_active(self) -> bool:
        return self.status is RightStatus.DECREED

    @property
    def can_be_called(self) -> bool:
        """Only a decreed direct flow right can place a call on the stream."""

        return self.is_active and self.kind is RightKind.DIRECT_FLOW

    def is_senior_to(self, other: WaterRight) -> bool:
        return self.priority.is_senior_to(other.priority)

    def rate_or_zero(self) -> Decimal:
        return self.rate_cfs if self.rate_cfs is not None else Decimal("0")


def order_by_priority(rights: list[WaterRight]) -> list[WaterRight]:
    """Most senior first, which is the order every administration walks."""

    return sorted(rights, key=lambda right: (right.priority, right.decree.text))


def juniors_to(rights: list[WaterRight], calling: WaterRight) -> list[WaterRight]:
    """Everything junior to a calling right, most junior first."""

    junior = [right for right in rights if calling.is_senior_to(right)]
    return list(reversed(order_by_priority(junior)))
