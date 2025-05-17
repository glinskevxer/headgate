"""What the ground got against what the crop on it needed.

Two numbers already exist for every parcel: what the crop requires over a
season, from the state's table, and what was actually delivered to the turnout
it sits under. Putting them beside each other answers the question the board
asks about every dry year, which is whether the shortage is the creek or the
irrigating.

A parcel well over its requirement is not being cheated by the ditch. A parcel
well under it either did not get its water or is not being measured, and this
tells the office which of its turnouts to look at first.

The comparison is against gross requirement, not net, because the water is
measured at the turnout and everything between the turnout and the plant is the
irrigator's own loss.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal

from ..duty.requirement import Application, gross_acre_feet
from ..errors import PolicyError, ValidationError
from ..ids import TurnoutCode
from ..model.parcel import PlaceOfUse
from ..units import round_volume

SHORT_FRACTION = Decimal("0.8")
GENEROUS_FRACTION = Decimal("1.25")


@dataclass(frozen=True, slots=True)
class TurnoutDuty:
    """One turnout, its ground, and what it got."""

    turnout: TurnoutCode
    acres: Decimal
    required_af: Decimal
    delivered_af: Decimal

    @property
    def ratio(self) -> Decimal:
        if self.required_af <= 0:
            return Decimal("0")
        return (self.delivered_af / self.required_af).quantize(Decimal("0.001"))

    @property
    def depth_inches(self) -> Decimal:
        if self.acres <= 0:
            return Decimal("0")
        return (self.delivered_af / self.acres * 12).quantize(Decimal("0.01"))

    @property
    def is_short(self) -> bool:
        return self.required_af > 0 and self.ratio < SHORT_FRACTION

    @property
    def is_generous(self) -> bool:
        return self.required_af > 0 and self.ratio > GENEROUS_FRACTION

    @property
    def shortfall_af(self) -> Decimal:
        short = self.required_af - self.delivered_af
        return round_volume(short) if short > 0 else Decimal("0")

    def describe(self) -> str:
        if self.required_af <= 0:
            return f"{self.turnout} irrigated nothing this season"
        word = "short" if self.is_short else ("over" if self.is_generous else "about right")
        return (
            f"{self.turnout} took {self.delivered_af} of {self.required_af} acre feet, "
            f"{word}, at {self.depth_inches} inches"
        )


@dataclass(frozen=True, slots=True)
class DutyReview:
    """Every turnout on the ditch against the ground behind it."""

    water_year: int
    duties: tuple[TurnoutDuty, ...]

    @property
    def required_af(self) -> Decimal:
        return round_volume(sum((item.required_af for item in self.duties), Decimal("0")))

    @property
    def delivered_af(self) -> Decimal:
        return round_volume(sum((item.delivered_af for item in self.duties), Decimal("0")))

    @property
    def ratio(self) -> Decimal:
        if self.required_af <= 0:
            return Decimal("0")
        return (self.delivered_af / self.required_af).quantize(Decimal("0.001"))

    @property
    def short(self) -> tuple[TurnoutDuty, ...]:
        return tuple(item for item in self.duties if item.is_short)

    @property
    def generous(self) -> tuple[TurnoutDuty, ...]:
        return tuple(item for item in self.duties if item.is_generous)

    def for_turnout(self, turnout: TurnoutCode) -> TurnoutDuty:
        for item in self.duties:
            if item.turnout == turnout:
                return item
        raise PolicyError(f"turnout {turnout} is not in this review")

    def summary(self) -> list[tuple[str, str]]:
        return [
            ("water year", str(self.water_year)),
            ("required", f"{self.required_af} acre feet"),
            ("delivered", f"{self.delivered_af} acre feet"),
            ("ratio", f"{self.ratio}"),
            ("short", str(len(self.short))),
            ("over", str(len(self.generous))),
        ]


def review(
    water_year: int,
    place: PlaceOfUse,
    delivered: Mapping[TurnoutCode, Decimal],
    application: Application,
    on: object,
) -> DutyReview:
    """Line every turnout's water up against the crop behind it."""

    from datetime import date as _date

    if not isinstance(on, _date):
        raise ValidationError("a duty review is worked as of a day")
    duties: list[TurnoutDuty] = []
    turnouts = sorted(set(place.turnouts(on)) | set(delivered), key=str)
    for turnout in turnouts:
        acres = place.acres_under(turnout, on)
        required = Decimal("0")
        for parcel in place.parcels:
            if parcel.turnout != turnout or not parcel.in_production_on(on):
                continue
            required += gross_acre_feet(parcel.crop, parcel.irrigated_acres, application)
        duties.append(
            TurnoutDuty(
                turnout=turnout,
                acres=acres,
                required_af=round_volume(required),
                delivered_af=round_volume(delivered.get(turnout, Decimal("0"))),
            )
        )
    return DutyReview(water_year=water_year, duties=tuple(duties))
