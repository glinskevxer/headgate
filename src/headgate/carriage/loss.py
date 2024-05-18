"""What it costs to carry water down the ditch.

Loss is charged by the mile and by the ditch, so the same delivery costs more
at the end of a lateral than at the head of the main. The walk from the
headgate to a turnout is already known; this puts a number on each leg of it.

The number is a fraction of what enters the leg, not a flat rate, so the legs
compound. Sending twice as much down a lateral loses twice as much, which is
the model the district has always billed against and is close enough for a
season on a lined ditch.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from ..errors import PolicyError, ValidationError
from ..ids import TurnoutCode
from ..model.ditch import Ditch, DitchSystem
from ..model.stream import FEET_PER_MILE
from ..units import round_rate


@dataclass(frozen=True, slots=True)
class Leg:
    """One ditch, for the distance the water ran down it."""

    ditch: Ditch
    feet: Decimal
    entering_cfs: Decimal
    leaving_cfs: Decimal

    @property
    def miles(self) -> Decimal:
        return self.feet / FEET_PER_MILE

    @property
    def lost_cfs(self) -> Decimal:
        return round_rate(self.entering_cfs - self.leaving_cfs)

    @property
    def carried_fraction(self) -> Decimal:
        if self.entering_cfs == 0:
            return Decimal("1")
        return self.leaving_cfs / self.entering_cfs


@dataclass(frozen=True, slots=True)
class Carriage:
    """The whole run from the headgate to one turnout."""

    turnout: TurnoutCode
    legs: tuple[Leg, ...]

    @property
    def headgate_cfs(self) -> Decimal:
        return self.legs[0].entering_cfs if self.legs else Decimal("0")

    @property
    def delivered_cfs(self) -> Decimal:
        return self.legs[-1].leaving_cfs if self.legs else Decimal("0")

    @property
    def lost_cfs(self) -> Decimal:
        return round_rate(self.headgate_cfs - self.delivered_cfs)

    @property
    def carried_fraction(self) -> Decimal:
        if self.headgate_cfs == 0:
            return Decimal("1")
        return self.delivered_cfs / self.headgate_cfs

    @property
    def miles(self) -> Decimal:
        return sum((leg.miles for leg in self.legs), Decimal("0"))


def carried_fraction(system: DitchSystem, turnout: TurnoutCode) -> Decimal:
    """The share of a headgate flow that reaches a turnout."""

    fraction = Decimal("1")
    for ditch, feet in system.path_to(turnout):
        miles = feet / FEET_PER_MILE
        leg = Decimal("1") - ditch.loss_fraction_per_mile * miles
        if leg <= 0:
            raise PolicyError(
                f"ditch {ditch.code} loses everything over {miles} miles, so nothing reaches "
                f"{turnout}"
            )
        fraction *= leg
    return fraction


def carriage_for(system: DitchSystem, turnout: TurnoutCode, headgate_cfs: Decimal) -> Carriage:
    """Run a flow from the headgate to a turnout, leg by leg."""

    if headgate_cfs < 0:
        raise ValidationError("a headgate cannot pass a negative flow")
    legs: list[Leg] = []
    flowing = headgate_cfs
    for ditch, feet in system.path_to(turnout):
        miles = feet / FEET_PER_MILE
        share = Decimal("1") - ditch.loss_fraction_per_mile * miles
        if share <= 0:
            raise PolicyError(
                f"ditch {ditch.code} loses everything over {miles} miles, so nothing reaches "
                f"{turnout}"
            )
        leaving = round_rate(flowing * share)
        legs.append(Leg(ditch=ditch, feet=feet, entering_cfs=flowing, leaving_cfs=leaving))
        flowing = leaving
    return Carriage(turnout=turnout, legs=tuple(legs))


def headgate_needed_for(system: DitchSystem, turnout: TurnoutCode, wanted_cfs: Decimal) -> Decimal:
    """How much to turn in at the headgate to deliver a rate at a turnout."""

    if wanted_cfs < 0:
        raise ValidationError("a delivery may not be negative")
    return round_rate(wanted_cfs / carried_fraction(system, turnout))


def loss_between(system: DitchSystem, turnout: TurnoutCode, headgate_cfs: Decimal) -> Decimal:
    """What the ditch keeps when a flow is sent to one turnout."""

    return carriage_for(system, turnout, headgate_cfs).lost_cfs


def capacity_check(system: DitchSystem, turnout: TurnoutCode, headgate_cfs: Decimal) -> None:
    """Refuse a flow no ditch on the path could actually carry."""

    carriage = carriage_for(system, turnout, headgate_cfs)
    for leg in carriage.legs:
        if leg.entering_cfs > leg.ditch.capacity_cfs:
            raise PolicyError(
                f"{leg.entering_cfs} cfs is more than ditch {leg.ditch.code} carries "
                f"({leg.ditch.capacity_cfs} cfs)"
            )
    gate = system.find_turnout(turnout)[1]
    if carriage.delivered_cfs > gate.capacity_cfs:
        raise PolicyError(
            f"{carriage.delivered_cfs} cfs is more than turnout {turnout} passes "
            f"({gate.capacity_cfs} cfs)"
        )
