"""Building a cycle of the rotation.

Each turnout gets the ditch to itself for a share of the cycle, in proportion
to the shares behind it. The rate is whatever the ditch can put down that
particular path, which is not the same for every turnout: a small turnout at
the end of a lateral cannot take the whole stream even when it is its turn.

Two turnouts get dropped rather than served. One whose share of the cycle comes
out under the minimum set, because sending a rider out to open a gate for two
hours costs more than the water is worth. And one the commissioner has already
curtailed, which is not the rotation's decision to make.

Whoever gets dropped keeps their shares, so the next cycle they are weighted
the same. The district does not make it up to them and never has.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal

from ..errors import PolicyError, ValidationError
from ..ids import TurnoutCode
from ..model.ditch import DitchSystem
from ..units import round_rate
from ..wateryear import Span
from .plan import RotationPlan, RunWindow

MINIMUM_SET_HOURS = Decimal("4")
SECONDS_PER_HOUR = Decimal("3600")


@dataclass(frozen=True, slots=True)
class Turn:
    """One turnout's claim on the cycle."""

    turnout: TurnoutCode
    shares: Decimal

    def __post_init__(self) -> None:
        if self.shares <= 0:
            raise ValidationError(f"turnout {self.turnout} takes a turn on no shares")


@dataclass(frozen=True, slots=True)
class Cycle:
    """A built cycle, and everybody who did not fit in it."""

    plan: RotationPlan
    skipped: tuple[TurnoutCode, ...]
    short_set: tuple[TurnoutCode, ...]

    @property
    def served(self) -> tuple[TurnoutCode, ...]:
        return self.plan.turnouts

    @property
    def is_complete(self) -> bool:
        return not self.skipped and not self.short_set


def deliverable_rate(system: DitchSystem, turnout: TurnoutCode, available_cfs: Decimal) -> Decimal:
    """The most that can be put down one path, whatever is in the creek."""

    gate = system.find_turnout(turnout)[1]
    rate = available_cfs
    for ditch, _ in system.path_to(turnout):
        rate = min(rate, ditch.capacity_cfs)
    return round_rate(min(rate, gate.capacity_cfs))


def build_cycle(
    system: DitchSystem,
    water_year: int,
    turns: list[Turn],
    available_cfs: Decimal,
    start: datetime,
    cycle_hours: Decimal,
    curtailed: tuple[TurnoutCode, ...] = (),
    minimum_hours: Decimal = MINIMUM_SET_HOURS,
) -> Cycle:
    """Lay one cycle of the rotation out end to end from a start time."""

    if available_cfs <= 0:
        raise PolicyError("there is no water to rotate")
    if cycle_hours <= 0:
        raise ValidationError("a cycle has to be longer than no time at all")
    if not turns:
        raise PolicyError("nobody has asked for a turn")
    eligible = [turn for turn in turns if turn.turnout not in curtailed]
    skipped = tuple(sorted(turn.turnout for turn in turns if turn.turnout in curtailed))
    if not eligible:
        return Cycle(RotationPlan(water_year=water_year), skipped, ())
    total_shares = sum((turn.shares for turn in eligible), Decimal("0"))
    hours = {
        turn.turnout: (cycle_hours * turn.shares / total_shares).quantize(Decimal("0.01"))
        for turn in eligible
    }
    short = tuple(sorted(code for code, allowed in hours.items() if allowed < minimum_hours))
    running = [turn for turn in eligible if turn.turnout not in short]
    if not running:
        return Cycle(RotationPlan(water_year=water_year), skipped, short)
    if short:
        total_shares = sum((turn.shares for turn in running), Decimal("0"))
        hours = {
            turn.turnout: (cycle_hours * turn.shares / total_shares).quantize(Decimal("0.01"))
            for turn in running
        }
    plan = RotationPlan(water_year=water_year)
    cursor = start
    for turn in running:
        length = hours[turn.turnout]
        end = cursor + timedelta(seconds=float(length * SECONDS_PER_HOUR))
        plan = plan.add(
            RunWindow(
                turnout=turn.turnout,
                span=Span(cursor, end),
                rate_cfs=deliverable_rate(system, turn.turnout, available_cfs),
            )
        )
        cursor = end
    return Cycle(plan, skipped, short)


def repeat_cycle(
    system: DitchSystem,
    water_year: int,
    turns: list[Turn],
    available_cfs: Decimal,
    start: datetime,
    cycle_hours: Decimal,
    cycles: int,
    curtailed: tuple[TurnoutCode, ...] = (),
) -> RotationPlan:
    """Run the same cycle over and over, which is what a dry July looks like."""

    if cycles < 1:
        raise ValidationError("a rotation runs at least one cycle")
    plan = RotationPlan(water_year=water_year)
    cursor = start
    for _ in range(cycles):
        built = build_cycle(
            system, water_year, turns, available_cfs, cursor, cycle_hours, curtailed
        )
        for window in built.plan.windows:
            plan = plan.add(window)
        cursor = cursor + timedelta(seconds=float(cycle_hours * SECONDS_PER_HOUR))
    return plan


def shares_served(cycle: Cycle, turns: list[Turn]) -> Decimal:
    """The shares that actually got a set out of a cycle."""

    served = set(cycle.served)
    return sum((turn.shares for turn in turns if turn.turnout in served), Decimal("0"))
