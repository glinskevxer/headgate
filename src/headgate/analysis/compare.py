"""Comparing one season against another, and against the run of them.

The board asks the same three questions every November. Was it a short year.
Did the ditch lose more than it usually does. And is that turnout down because
the creek was down or because something is wrong with it.

The last one is the reason this exists. A turnout that delivered thirty percent
less in a year the whole district delivered thirty percent less is normal. The
same turnout down thirty percent in an average year is a broken gate, a bad
staff, or somebody irrigating at night, and the difference between those two
readings is the only thing that tells the office where to send a rider.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal

from ..errors import PolicyError, ValidationError
from ..ids import TurnoutCode
from ..units import round_volume


@dataclass(frozen=True, slots=True)
class SeasonTotals:
    """One season, as far as a comparison cares."""

    water_year: int
    headgate_af: Decimal
    delivered_af: Decimal
    by_turnout: dict[TurnoutCode, Decimal]

    def __post_init__(self) -> None:
        if self.headgate_af < 0 or self.delivered_af < 0:
            raise ValidationError(f"the {self.water_year} season carries negative water")
        if self.delivered_af > self.headgate_af:
            raise PolicyError(f"the {self.water_year} turnouts took more than the headgate passed")

    @property
    def loss_af(self) -> Decimal:
        return round_volume(self.headgate_af - self.delivered_af)

    @property
    def carriage(self) -> Decimal:
        if self.headgate_af == 0:
            return Decimal("0")
        return (self.delivered_af / self.headgate_af).quantize(Decimal("0.001"))

    def for_turnout(self, turnout: TurnoutCode) -> Decimal:
        return self.by_turnout.get(turnout, Decimal("0"))


def _change(before: Decimal, after: Decimal) -> Decimal:
    if before == 0:
        return Decimal("0")
    return ((after - before) / before * 100).quantize(Decimal("0.1"))


@dataclass(frozen=True, slots=True)
class TurnoutChange:
    """One turnout, this year against last."""

    turnout: TurnoutCode
    before_af: Decimal
    after_af: Decimal
    district_change: Decimal

    @property
    def change(self) -> Decimal:
        return _change(self.before_af, self.after_af)

    @property
    def against_the_district(self) -> Decimal:
        """How far this turnout moved beyond what the whole district did."""

        return (self.change - self.district_change).quantize(Decimal("0.1"))

    def is_out_of_step(self, tolerance: Decimal = Decimal("20")) -> bool:
        if tolerance < 0:
            raise ValidationError("a tolerance may not be negative")
        return abs(self.against_the_district) > tolerance


@dataclass(frozen=True, slots=True)
class Comparison:
    """Two seasons, and what moved between them."""

    before: SeasonTotals
    after: SeasonTotals
    changes: tuple[TurnoutChange, ...]

    @property
    def delivered_change(self) -> Decimal:
        return _change(self.before.delivered_af, self.after.delivered_af)

    @property
    def headgate_change(self) -> Decimal:
        return _change(self.before.headgate_af, self.after.headgate_af)

    @property
    def loss_change(self) -> Decimal:
        return _change(self.before.loss_af, self.after.loss_af)

    @property
    def carriage_change(self) -> Decimal:
        return (self.after.carriage - self.before.carriage).quantize(Decimal("0.001"))

    def out_of_step(self, tolerance: Decimal = Decimal("20")) -> tuple[TurnoutChange, ...]:
        return tuple(item for item in self.changes if item.is_out_of_step(tolerance))

    def for_turnout(self, turnout: TurnoutCode) -> TurnoutChange:
        for item in self.changes:
            if item.turnout == turnout:
                return item
        raise PolicyError(f"turnout {turnout} is not in this comparison")

    def summary(self) -> list[tuple[str, str]]:
        return [
            ("years", f"{self.before.water_year} to {self.after.water_year}"),
            ("headgate", f"{self.headgate_change} percent"),
            ("delivered", f"{self.delivered_change} percent"),
            ("ditch loss", f"{self.loss_change} percent"),
            ("carriage", f"{self.carriage_change}"),
            ("out of step", str(len(self.out_of_step()))),
        ]


def compare(before: SeasonTotals, after: SeasonTotals) -> Comparison:
    """Line two seasons up, turnout by turnout."""

    if after.water_year <= before.water_year:
        raise PolicyError(f"{after.water_year} does not come after {before.water_year}")
    district = _change(before.delivered_af, after.delivered_af)
    turnouts = sorted(set(before.by_turnout) | set(after.by_turnout), key=str)
    changes = tuple(
        TurnoutChange(
            turnout=turnout,
            before_af=before.for_turnout(turnout),
            after_af=after.for_turnout(turnout),
            district_change=district,
        )
        for turnout in turnouts
    )
    return Comparison(before=before, after=after, changes=changes)


def average_delivery(seasons: Mapping[int, SeasonTotals], turnout: TurnoutCode) -> Decimal:
    """What a turnout usually takes, over whatever years are to hand."""

    if not seasons:
        raise PolicyError("there are no seasons to average")
    total = sum((item.for_turnout(turnout) for item in seasons.values()), Decimal("0"))
    return round_volume(total / Decimal(len(seasons)))
