"""The shape every rating in this package has.

A structure rating is a power curve. The coefficient and the exponent come from
the structure, the head offset accounts for a staff that was set a little off,
and the range is the part of the curve anybody is willing to defend. Reading
outside that range is not an error in the reading, it is the rating running out,
so it raises HeadOutOfRangeError and the caller decides what the record is worth.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Protocol, runtime_checkable

from ..errors import HeadOutOfRangeError, ValidationError
from ..units import round_rate


@runtime_checkable
class RatingCurve(Protocol):
    """Anything that turns a gauge height into a flow."""

    @property
    def min_head_feet(self) -> Decimal: ...

    @property
    def max_head_feet(self) -> Decimal: ...

    def discharge_cfs(self, head_feet: Decimal) -> Decimal: ...

    def describe(self) -> str: ...


@dataclass(frozen=True, slots=True)
class PowerCurve:
    """Discharge as a coefficient times an effective head to an exponent."""

    coefficient: Decimal
    exponent: Decimal
    low_head_feet: Decimal
    high_head_feet: Decimal
    label: str
    head_offset_feet: Decimal = Decimal("0")

    def __post_init__(self) -> None:
        if self.coefficient <= 0:
            raise ValidationError(f"rating {self.label} has a coefficient of {self.coefficient}")
        if self.exponent <= 0:
            raise ValidationError(f"rating {self.label} has an exponent of {self.exponent}")
        if self.high_head_feet <= self.low_head_feet:
            raise ValidationError(f"rating {self.label} covers no range of head")
        if self.low_head_feet + self.head_offset_feet <= 0:
            raise ValidationError(f"rating {self.label} starts at or below zero effective head")

    @property
    def min_head_feet(self) -> Decimal:
        return self.low_head_feet

    @property
    def max_head_feet(self) -> Decimal:
        return self.high_head_feet

    def covers(self, head_feet: Decimal) -> bool:
        return self.low_head_feet <= head_feet <= self.high_head_feet

    def effective_head(self, head_feet: Decimal) -> Decimal:
        return head_feet + self.head_offset_feet

    def discharge_cfs(self, head_feet: Decimal) -> Decimal:
        if not self.covers(head_feet):
            raise HeadOutOfRangeError(head_feet, self.low_head_feet, self.high_head_feet)
        return round_rate(self.coefficient * self.effective_head(head_feet) ** self.exponent)

    def head_for(self, discharge_cfs: Decimal) -> Decimal:
        """The gauge height that would pass a flow, for setting a gate."""

        if discharge_cfs <= 0:
            raise ValidationError("a gate is not set by asking for no water")
        raw = (discharge_cfs / self.coefficient) ** (Decimal("1") / self.exponent)
        head = raw - self.head_offset_feet
        if not self.covers(head):
            raise HeadOutOfRangeError(head, self.low_head_feet, self.high_head_feet)
        return head.quantize(Decimal("0.001"))

    def capacity_cfs(self) -> Decimal:
        return self.discharge_cfs(self.high_head_feet)

    def describe(self) -> str:
        offset = f" with a {self.head_offset_feet} ft staff offset" if self.head_offset_feet else ""
        return (
            f"{self.label}: Q = {self.coefficient} H^{self.exponent}{offset}, "
            f"good from {self.low_head_feet} to {self.high_head_feet} ft"
        )
