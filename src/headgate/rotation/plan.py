"""The rotation, which is what a ditch does when it cannot serve everybody.

Below a certain flow a lateral cannot run four turnouts at once and put a
useful head on any of them, so the district stops trying. Each turnout gets the
whole lateral for a stretch of hours and then shuts and passes it on. The plan
is the list of those stretches.

Two rules make it a plan rather than a wish. Nothing may run outside the
declared season, and the flows running at any one moment on any one ditch have
to fit in that ditch. The second is checked against the whole system rather
than one lateral, because a sublateral running at the same time as its parent
is drawing through the parent as well.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime
from decimal import Decimal

from ..errors import PolicyError, ValidationError
from ..ids import DitchCode, TurnoutCode
from ..model.ditch import DitchSystem
from ..units import round_rate
from ..wateryear import IrrigationSeason, Span


@dataclass(frozen=True, slots=True)
class RunWindow:
    """One turnout, running at one rate, for one stretch of time."""

    turnout: TurnoutCode
    span: Span
    rate_cfs: Decimal

    def __post_init__(self) -> None:
        if self.rate_cfs <= 0:
            raise ValidationError(f"the window at {self.turnout} runs at {self.rate_cfs} cfs")

    @property
    def hours(self) -> Decimal:
        return (self.span.seconds / Decimal("3600")).quantize(Decimal("0.01"))

    @property
    def volume_af(self) -> Decimal:
        return (self.rate_cfs * self.span.seconds / Decimal("43560")).quantize(Decimal("0.0001"))

    def running_at(self, moment: datetime) -> bool:
        return self.span.contains(moment)


@dataclass(frozen=True, slots=True)
class RotationPlan:
    """Every window on the ditch for one stretch of the season."""

    water_year: int
    windows: tuple[RunWindow, ...] = ()

    def windows_for(self, turnout: TurnoutCode) -> tuple[RunWindow, ...]:
        return tuple(window for window in self.windows if window.turnout == turnout)

    def running_at(self, moment: datetime) -> tuple[RunWindow, ...]:
        return tuple(window for window in self.windows if window.running_at(moment))

    def rate_at(self, turnout: TurnoutCode, moment: datetime) -> Decimal:
        return round_rate(
            sum(
                (
                    window.rate_cfs
                    for window in self.running_at(moment)
                    if window.turnout == turnout
                ),
                Decimal("0"),
            )
        )

    def hours_for(self, turnout: TurnoutCode) -> Decimal:
        return sum((window.hours for window in self.windows_for(turnout)), Decimal("0"))

    def volume_for(self, turnout: TurnoutCode) -> Decimal:
        return sum((window.volume_af for window in self.windows_for(turnout)), Decimal("0"))

    @property
    def turnouts(self) -> tuple[TurnoutCode, ...]:
        return tuple(sorted({window.turnout for window in self.windows}))

    @property
    def span(self) -> Span | None:
        if not self.windows:
            return None
        return Span(
            min(window.span.start for window in self.windows),
            max(window.span.end for window in self.windows),
        )

    def add(self, window: RunWindow) -> RotationPlan:
        return replace(self, windows=(*self.windows, window))

    def drop(self, turnout: TurnoutCode) -> RotationPlan:
        """Take a turnout off the rotation, which a curtailment does."""

        kept = tuple(window for window in self.windows if window.turnout != turnout)
        if len(kept) == len(self.windows):
            raise PolicyError(f"turnout {turnout} is not on this rotation")
        return replace(self, windows=kept)


def check_in_season(plan: RotationPlan, season: IrrigationSeason) -> None:
    """Refuse a plan that runs water outside the declared season."""

    if season.water_year != plan.water_year:
        raise PolicyError(
            f"a plan for {plan.water_year} cannot be checked against the {season.water_year} season"
        )
    inside = season.as_span()
    for window in plan.windows:
        if window.span.start < inside.start or window.span.end > inside.end:
            raise PolicyError(
                f"the window at {window.turnout} runs {window.span.start:%Y-%m-%d} to "
                f"{window.span.end:%Y-%m-%d}, outside the declared season"
            )


def _flow_through(system: DitchSystem, ditch: DitchCode, running: tuple[RunWindow, ...]) -> Decimal:
    total = Decimal("0")
    for window in running:
        path = [leg.code for leg, _ in system.path_to(window.turnout)]
        if ditch in path:
            total += window.rate_cfs
    return total


def check_capacity(plan: RotationPlan, system: DitchSystem) -> None:
    """Refuse a plan that puts more in a ditch than the ditch carries."""

    moments = sorted({window.span.start for window in plan.windows})
    for moment in moments:
        running = plan.running_at(moment)
        for ditch in system.ditches:
            flowing = _flow_through(system, ditch.code, running)
            if flowing > ditch.capacity_cfs:
                raise PolicyError(
                    f"at {moment:%Y-%m-%d %H:%M} the plan puts {round_rate(flowing)} cfs "
                    f"into ditch {ditch.code}, which carries {ditch.capacity_cfs}"
                )


def check_plan(plan: RotationPlan, system: DitchSystem, season: IrrigationSeason) -> None:
    """Both checks, in the order that gives the clearest complaint first."""

    check_in_season(plan, season)
    check_capacity(plan, system)
