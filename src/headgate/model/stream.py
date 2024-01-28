"""The stream the ditch diverts from, cut into reaches.

Reaches are numbered downstream and measured in river miles, which count up
going upstream, so the head of a reach is the larger number. Two things hang
off a reach and both matter later: how long water takes to travel it, which
decides whether a call can be answered at all, and how much of the flow it
loses on the way, which decides whether answering the call is worth doing.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from ..errors import ValidationError

FEET_PER_MILE = Decimal("5280")


@dataclass(frozen=True, slots=True)
class Reach:
    """One measured piece of the stream."""

    code: str
    name: str
    head_mile: Decimal
    toe_mile: Decimal
    mean_velocity_fps: Decimal
    loss_fraction_per_mile: Decimal

    def __post_init__(self) -> None:
        if self.head_mile <= self.toe_mile:
            raise ValidationError(
                f"reach {self.code} runs from mile {self.head_mile} to {self.toe_mile}, "
                "which is upstream of where it started"
            )
        if self.mean_velocity_fps <= 0:
            raise ValidationError(f"reach {self.code} has no velocity to travel at")
        if self.loss_fraction_per_mile < 0 or self.loss_fraction_per_mile >= Decimal("0.5"):
            raise ValidationError(
                f"reach {self.code} loses {self.loss_fraction_per_mile} of the flow per mile, "
                "which is not a loss rate anybody would write down"
            )

    @property
    def length_miles(self) -> Decimal:
        return self.head_mile - self.toe_mile

    @property
    def travel_seconds(self) -> Decimal:
        return self.length_miles * FEET_PER_MILE / self.mean_velocity_fps

    def contains(self, mile: Decimal) -> bool:
        return self.toe_mile <= mile < self.head_mile

    def carried_fraction(self, miles: Decimal) -> Decimal:
        """The share of a flow that survives a distance inside this reach."""

        if miles < 0 or miles > self.length_miles:
            raise ValidationError(f"{miles} miles is not a distance inside reach {self.code}")
        return Decimal("1") - self.loss_fraction_per_mile * miles


@dataclass(frozen=True, slots=True)
class GagePoint:
    """A place on the stream where somebody reads a staff."""

    code: str
    name: str
    mile: Decimal
    datum_elevation_feet: Decimal


@dataclass(frozen=True, slots=True)
class Stream:
    """A stream, described head to toe by contiguous reaches."""

    name: str
    reaches: tuple[Reach, ...]

    def __post_init__(self) -> None:
        if not self.reaches:
            raise ValidationError(f"stream {self.name} has no reaches")
        seen: set[str] = set()
        for reach in self.reaches:
            if reach.code in seen:
                raise ValidationError(f"stream {self.name} lists reach {reach.code} twice")
            seen.add(reach.code)
        for upper, lower in zip(self.reaches, self.reaches[1:], strict=False):
            if upper.toe_mile != lower.head_mile:
                raise ValidationError(
                    f"reach {upper.code} ends at mile {upper.toe_mile} and reach "
                    f"{lower.code} starts at mile {lower.head_mile}, leaving a gap"
                )

    @property
    def head_mile(self) -> Decimal:
        return self.reaches[0].head_mile

    @property
    def toe_mile(self) -> Decimal:
        return self.reaches[-1].toe_mile

    def reach_at(self, mile: Decimal) -> Reach:
        for reach in self.reaches:
            if reach.contains(mile):
                return reach
        raise ValidationError(f"mile {mile} is not on {self.name}")

    def travel_seconds(self, upper_mile: Decimal, lower_mile: Decimal) -> Decimal:
        """How long water takes to run from one point down to another."""

        total = Decimal("0")
        for reach, miles in self._pieces(upper_mile, lower_mile):
            total += miles * FEET_PER_MILE / reach.mean_velocity_fps
        return total

    def carried_fraction(self, upper_mile: Decimal, lower_mile: Decimal) -> Decimal:
        """The share of a released flow that arrives at the lower point."""

        carried = Decimal("1")
        for reach, miles in self._pieces(upper_mile, lower_mile):
            carried *= reach.carried_fraction(miles)
        return carried

    def _pieces(self, upper_mile: Decimal, lower_mile: Decimal) -> list[tuple[Reach, Decimal]]:
        if lower_mile > upper_mile:
            raise ValidationError(
                f"mile {lower_mile} is upstream of mile {upper_mile}, "
                "so water does not run that way"
            )
        if upper_mile > self.head_mile or lower_mile < self.toe_mile:
            raise ValidationError(f"miles {upper_mile} to {lower_mile} leave {self.name}")
        pieces: list[tuple[Reach, Decimal]] = []
        for reach in self.reaches:
            top = min(upper_mile, reach.head_mile)
            bottom = max(lower_mile, reach.toe_mile)
            if top > bottom:
                pieces.append((reach, top - bottom))
        return pieces
