"""The canal system: the main ditch, its laterals and the turnouts on them.

Every delivery is made at a turnout, and every turnout sits a measured distance
down a lateral that itself leaves its parent a measured distance down. That
chain is what conveyance loss is charged against, so the system knows how to
walk from the headgate to any turnout and say how far the water went and whose
ditch it went down.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from ..errors import NotFoundError, ValidationError
from ..ids import DitchCode, TurnoutCode
from .stream import FEET_PER_MILE


@dataclass(frozen=True, slots=True)
class Turnout:
    """A gate in the bank of a ditch, serving one place of use."""

    code: TurnoutCode
    name: str
    station_feet: Decimal
    capacity_cfs: Decimal
    served_acres: Decimal

    def __post_init__(self) -> None:
        if self.station_feet < 0:
            raise ValidationError(f"turnout {self.code} sits at a negative station")
        if self.capacity_cfs <= 0:
            raise ValidationError(f"turnout {self.code} has no capacity")
        if self.served_acres < 0:
            raise ValidationError(f"turnout {self.code} serves a negative acreage")


@dataclass(frozen=True, slots=True)
class Ditch:
    """The main canal or one of its laterals."""

    code: DitchCode
    name: str
    capacity_cfs: Decimal
    length_feet: Decimal
    loss_fraction_per_mile: Decimal
    turnouts: tuple[Turnout, ...] = ()
    parent: DitchCode | None = None
    offtake_station_feet: Decimal | None = None
    diversion_mile: Decimal | None = None

    def __post_init__(self) -> None:
        if self.capacity_cfs <= 0:
            raise ValidationError(f"ditch {self.code} has no capacity")
        if self.length_feet <= 0:
            raise ValidationError(f"ditch {self.code} has no length")
        if self.loss_fraction_per_mile < 0 or self.loss_fraction_per_mile >= Decimal("0.5"):
            raise ValidationError(f"ditch {self.code} has an impossible loss rate")
        if self.parent is None:
            if self.diversion_mile is None:
                raise ValidationError(f"ditch {self.code} heads on no stream and no parent ditch")
            if self.offtake_station_feet is not None:
                raise ValidationError(f"ditch {self.code} has no parent to leave at a station")
        else:
            if self.offtake_station_feet is None:
                raise ValidationError(
                    f"lateral {self.code} does not say where it leaves {self.parent}"
                )
            if self.offtake_station_feet < 0:
                raise ValidationError(
                    f"lateral {self.code} leaves its parent at a negative station"
                )
            if self.diversion_mile is not None:
                raise ValidationError(f"lateral {self.code} may not also head on the stream")
        seen: set[TurnoutCode] = set()
        for turnout in self.turnouts:
            if turnout.code.ditch != self.code:
                raise ValidationError(f"turnout {turnout.code} is not on ditch {self.code}")
            if turnout.code in seen:
                raise ValidationError(f"ditch {self.code} lists turnout {turnout.code} twice")
            if turnout.station_feet > self.length_feet:
                raise ValidationError(
                    f"turnout {turnout.code} sits at station {turnout.station_feet} "
                    f"on a ditch {self.length_feet} feet long"
                )
            seen.add(turnout.code)

    @property
    def is_main(self) -> bool:
        return self.parent is None

    @property
    def length_miles(self) -> Decimal:
        return self.length_feet / FEET_PER_MILE

    def turnout(self, code: TurnoutCode) -> Turnout:
        for turnout in self.turnouts:
            if turnout.code == code:
                return turnout
        raise NotFoundError("turnout", str(code))


@dataclass(frozen=True, slots=True)
class DitchSystem:
    """Every ditch the company runs, with one main canal at the head."""

    ditches: tuple[Ditch, ...]

    def __post_init__(self) -> None:
        if not self.ditches:
            raise ValidationError("a ditch system with no ditches is not a ditch system")
        codes: set[DitchCode] = set()
        for ditch in self.ditches:
            if ditch.code in codes:
                raise ValidationError(f"ditch {ditch.code} is listed twice")
            codes.add(ditch.code)
        mains = [ditch for ditch in self.ditches if ditch.is_main]
        if len(mains) != 1:
            raise ValidationError(
                f"a ditch system runs one main canal, this one lists {len(mains)}"
            )
        turnouts: set[TurnoutCode] = set()
        for ditch in self.ditches:
            for turnout in ditch.turnouts:
                if turnout.code in turnouts:
                    raise ValidationError(f"turnout {turnout.code} is listed on two ditches")
                turnouts.add(turnout.code)
            if ditch.parent is None:
                continue
            if ditch.parent not in codes:
                raise ValidationError(
                    f"ditch {ditch.code} leaves {ditch.parent}, which is not here"
                )
            parent = self.ditch(ditch.parent)
            station = ditch.offtake_station_feet
            assert station is not None
            if station > parent.length_feet:
                raise ValidationError(
                    f"ditch {ditch.code} leaves {parent.code} at station {station}, "
                    f"past its {parent.length_feet} foot end"
                )
        self._check_for_loops()

    def _check_for_loops(self) -> None:
        for ditch in self.ditches:
            seen = {ditch.code}
            current = ditch
            while current.parent is not None:
                if current.parent in seen:
                    raise ValidationError(
                        f"ditch {ditch.code} runs into itself through its parents"
                    )
                seen.add(current.parent)
                current = self.ditch(current.parent)

    @property
    def main(self) -> Ditch:
        return next(ditch for ditch in self.ditches if ditch.is_main)

    def ditch(self, code: DitchCode) -> Ditch:
        for ditch in self.ditches:
            if ditch.code == code:
                return ditch
        raise NotFoundError("ditch", str(code))

    def children(self, code: DitchCode) -> tuple[Ditch, ...]:
        return tuple(ditch for ditch in self.ditches if ditch.parent == code)

    def all_turnouts(self) -> tuple[Turnout, ...]:
        return tuple(turnout for ditch in self.ditches for turnout in ditch.turnouts)

    def find_turnout(self, code: TurnoutCode) -> tuple[Ditch, Turnout]:
        for ditch in self.ditches:
            for turnout in ditch.turnouts:
                if turnout.code == code:
                    return ditch, turnout
        raise NotFoundError("turnout", str(code))

    def path_to(self, code: TurnoutCode) -> tuple[tuple[Ditch, Decimal], ...]:
        """Each ditch the water runs down to reach a turnout, and how far."""

        ditch, turnout = self.find_turnout(code)
        legs: list[tuple[Ditch, Decimal]] = [(ditch, turnout.station_feet)]
        current = ditch
        while current.parent is not None:
            station = current.offtake_station_feet
            assert station is not None
            parent = self.ditch(current.parent)
            legs.append((parent, station))
            current = parent
        return tuple(reversed(legs))

    def carriage_feet(self, code: TurnoutCode) -> Decimal:
        return sum((feet for _, feet in self.path_to(code)), Decimal("0"))
