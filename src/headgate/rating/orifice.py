"""Orifice ratings.

An orifice measures on the difference between the water surface upstream and
downstream of the gate, not on a single staff, which is what makes it useful
where there is no fall to spare for a weir. It has to stay fully submerged to
be rated at all, and the district's constant head orifices hold a fixed two
tenths of a foot of differential and are set by opening the gate instead.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from ..errors import RatingError, ValidationError
from ..units import round_rate

GRAVITY_FPS2 = Decimal("32.174")
ORIFICE_COEFFICIENT = Decimal("0.61")
CONSTANT_HEAD_DIFFERENTIAL_FEET = Decimal("0.2")
MINIMUM_DIFFERENTIAL_FEET = Decimal("0.02")
MAXIMUM_DIFFERENTIAL_FEET = Decimal("2.0")


def velocity_head_fps(differential_feet: Decimal) -> Decimal:
    """The theoretical velocity through an opening under a differential."""

    if differential_feet <= 0:
        raise ValidationError("an orifice with no differential is not passing water")
    return (2 * GRAVITY_FPS2 * differential_feet).sqrt()


@dataclass(frozen=True, slots=True)
class SubmergedOrifice:
    """A rectangular submerged orifice with a fixed opening."""

    width_feet: Decimal
    height_feet: Decimal
    coefficient: Decimal = ORIFICE_COEFFICIENT

    def __post_init__(self) -> None:
        if self.width_feet <= 0 or self.height_feet <= 0:
            raise ValidationError("an orifice needs a width and a height")
        if self.coefficient <= 0 or self.coefficient > 1:
            raise ValidationError(
                f"a discharge coefficient of {self.coefficient} is not one anybody publishes"
            )

    @property
    def area_sqft(self) -> Decimal:
        return self.width_feet * self.height_feet

    @property
    def min_head_feet(self) -> Decimal:
        return MINIMUM_DIFFERENTIAL_FEET

    @property
    def max_head_feet(self) -> Decimal:
        return MAXIMUM_DIFFERENTIAL_FEET

    def discharge_cfs(self, head_feet: Decimal) -> Decimal:
        """Flow under a differential, the head here being the difference."""

        if head_feet < self.min_head_feet or head_feet > self.max_head_feet:
            raise RatingError(
                f"a differential of {head_feet} ft is outside the range an orifice is rated over"
            )
        return round_rate(self.coefficient * self.area_sqft * velocity_head_fps(head_feet))

    def differential_for(self, discharge_cfs: Decimal) -> Decimal:
        """The differential that would pass a flow through this opening."""

        if discharge_cfs <= 0:
            raise ValidationError("an orifice is not set by asking for no water")
        velocity = discharge_cfs / (self.coefficient * self.area_sqft)
        differential = velocity**2 / (2 * GRAVITY_FPS2)
        return differential.quantize(Decimal("0.001"))

    def describe(self) -> str:
        return (
            f"{self.width_feet} by {self.height_feet} ft submerged orifice, "
            f"coefficient {self.coefficient}"
        )


@dataclass(frozen=True, slots=True)
class ConstantHeadOrifice:
    """A constant head orifice, set by opening rather than by staff.

    The turnout holds two tenths of a foot across the gate and the delivery is
    changed by moving the gate. The rating is then a straight line in the
    opening, which is why the district likes them, and it is only true while
    somebody keeps the differential where it belongs.
    """

    width_feet: Decimal
    differential_feet: Decimal = CONSTANT_HEAD_DIFFERENTIAL_FEET
    coefficient: Decimal = ORIFICE_COEFFICIENT

    def __post_init__(self) -> None:
        if self.width_feet <= 0:
            raise ValidationError("a constant head orifice needs a gate width")
        if self.differential_feet <= 0:
            raise ValidationError("a constant head orifice holds a differential above zero")

    @property
    def min_head_feet(self) -> Decimal:
        return Decimal("0.05")

    @property
    def max_head_feet(self) -> Decimal:
        return Decimal("1.5")

    def discharge_cfs(self, head_feet: Decimal) -> Decimal:
        """Flow at a gate opening, the head here being the opening."""

        if head_feet < self.min_head_feet or head_feet > self.max_head_feet:
            raise RatingError(
                f"a gate opening of {head_feet} ft is outside what this orifice is rated for"
            )
        area = self.width_feet * head_feet
        return round_rate(self.coefficient * area * velocity_head_fps(self.differential_feet))

    def opening_for(self, discharge_cfs: Decimal) -> Decimal:
        """How far to open the gate to deliver a flow."""

        if discharge_cfs <= 0:
            raise ValidationError("a gate is not set by asking for no water")
        area = discharge_cfs / (self.coefficient * velocity_head_fps(self.differential_feet))
        return (area / self.width_feet).quantize(Decimal("0.001"))

    def describe(self) -> str:
        return (
            f"{self.width_feet} ft constant head orifice held at "
            f"{self.differential_feet} ft differential"
        )
