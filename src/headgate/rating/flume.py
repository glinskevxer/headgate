"""Flume ratings, and the submergence that voids them.

A Parshall flume measures on one head as long as the tailwater stays low
enough. Past that ratio the throat drowns, the free flow rating means nothing,
and the honest answer is that there is no measurement until the downstream
boards come out. The limit itself depends on the throat width, because a wide
flume tolerates more backwater than a narrow one.

A cutthroat flume has no throat section at all, which makes it cheap to drop
into an existing ditch. It is rated the same way and drowns sooner.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from ..errors import HeadOutOfRangeError, SubmergedFlowError, ValidationError
from ..units import round_rate

PARSHALL_COEFFICIENT = Decimal("4")
PARSHALL_EXPONENT_FACTOR = Decimal("1.522")
PARSHALL_EXPONENT_POWER = Decimal("0.026")

CUTTHROAT_COEFFICIENT = Decimal("4.50")
CUTTHROAT_WIDTH_POWER = Decimal("1.025")
CUTTHROAT_EXPONENT = Decimal("1.561")

NARROW_FLUME_FEET = Decimal("1")
NARROW_SUBMERGENCE_LIMIT = Decimal("0.6")
WIDE_SUBMERGENCE_LIMIT = Decimal("0.7")
CUTTHROAT_SUBMERGENCE_LIMIT = Decimal("0.65")


@dataclass(frozen=True, slots=True)
class ParshallFlume:
    """A Parshall flume rated for free flow on the upstream head."""

    throat_width_feet: Decimal
    head_offset_feet: Decimal = Decimal("0")

    def __post_init__(self) -> None:
        if self.throat_width_feet <= 0:
            raise ValidationError(f"a throat of {self.throat_width_feet} feet is not a flume")
        if self.throat_width_feet > Decimal("8"):
            raise ValidationError("this district has no flume wider than eight feet")

    @property
    def min_head_feet(self) -> Decimal:
        return Decimal("0.1")

    @property
    def max_head_feet(self) -> Decimal:
        return (self.throat_width_feet * Decimal("0.75") + Decimal("0.5")).quantize(
            Decimal("0.001")
        )

    @property
    def exponent(self) -> Decimal:
        return PARSHALL_EXPONENT_FACTOR * self.throat_width_feet**PARSHALL_EXPONENT_POWER

    @property
    def submergence_limit(self) -> Decimal:
        if self.throat_width_feet <= NARROW_FLUME_FEET:
            return NARROW_SUBMERGENCE_LIMIT
        return WIDE_SUBMERGENCE_LIMIT

    def discharge_cfs(self, head_feet: Decimal) -> Decimal:
        if head_feet < self.min_head_feet or head_feet > self.max_head_feet:
            raise HeadOutOfRangeError(head_feet, self.min_head_feet, self.max_head_feet)
        head = head_feet + self.head_offset_feet
        return round_rate(PARSHALL_COEFFICIENT * self.throat_width_feet * head**self.exponent)

    def submergence(self, upper_head_feet: Decimal, lower_head_feet: Decimal) -> Decimal:
        if upper_head_feet <= 0:
            raise ValidationError("a flume with no upstream head is not passing water")
        if lower_head_feet < 0:
            raise ValidationError("a tailwater reading may not be negative")
        return (lower_head_feet / upper_head_feet).quantize(Decimal("0.001"))

    def is_submerged(self, upper_head_feet: Decimal, lower_head_feet: Decimal) -> bool:
        return self.submergence(upper_head_feet, lower_head_feet) > self.submergence_limit

    def discharge_with_tailwater(
        self, upper_head_feet: Decimal, lower_head_feet: Decimal
    ) -> Decimal:
        """Free flow discharge, or nothing at all if the throat has drowned."""

        ratio = self.submergence(upper_head_feet, lower_head_feet)
        if ratio > self.submergence_limit:
            raise SubmergedFlowError(ratio, self.submergence_limit)
        return self.discharge_cfs(upper_head_feet)

    def describe(self) -> str:
        return (
            f"{self.throat_width_feet} ft Parshall flume, free flow to "
            f"{self.submergence_limit} submergence"
        )


@dataclass(frozen=True, slots=True)
class CutthroatFlume:
    """A flat bottomed cutthroat flume, rated on the upstream head."""

    throat_width_feet: Decimal
    head_offset_feet: Decimal = Decimal("0")

    def __post_init__(self) -> None:
        if self.throat_width_feet <= 0:
            raise ValidationError(f"a throat of {self.throat_width_feet} feet is not a flume")

    @property
    def min_head_feet(self) -> Decimal:
        return Decimal("0.1")

    @property
    def max_head_feet(self) -> Decimal:
        return (self.throat_width_feet * Decimal("0.6") + Decimal("0.4")).quantize(Decimal("0.001"))

    @property
    def submergence_limit(self) -> Decimal:
        return CUTTHROAT_SUBMERGENCE_LIMIT

    @property
    def coefficient(self) -> Decimal:
        return CUTTHROAT_COEFFICIENT * self.throat_width_feet**CUTTHROAT_WIDTH_POWER

    def discharge_cfs(self, head_feet: Decimal) -> Decimal:
        if head_feet < self.min_head_feet or head_feet > self.max_head_feet:
            raise HeadOutOfRangeError(head_feet, self.min_head_feet, self.max_head_feet)
        head = head_feet + self.head_offset_feet
        return round_rate(self.coefficient * head**CUTTHROAT_EXPONENT)

    def describe(self) -> str:
        return f"{self.throat_width_feet} ft cutthroat flume, free flow only"
