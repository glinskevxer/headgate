"""Seepage runs: measuring what a ditch loses instead of assuming it.

The loss rate on every ditch in this system starts as somebody's estimate. A
seepage run replaces it with a measurement: shut the turnouts on a reach, put a
flume in at each end, and the difference is what the bank is taking.

Three things make a run worth using and all three get checked. The turnouts
have to be shut, or the loss includes water somebody irrigated with. The
measurement has to be bigger than the error in the two flumes, or the answer is
noise dressed as a number. And the reach has to be long enough that the loss is
more than a rounding difference between the two gauges.

A reach can gain rather than lose. Ground water comes back into a ditch cut
below the water table, and a run that measures a gain is a real measurement,
not a mistake, so it is kept and flagged rather than thrown out.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from ..errors import PolicyError, ValidationError
from ..ids import DitchCode
from ..model.stream import FEET_PER_MILE
from ..units import round_rate

DEFAULT_FLUME_ERROR = Decimal("0.05")
MINIMUM_REACH_FEET = Decimal("1000")


@dataclass(frozen=True, slots=True)
class SeepageRun:
    """One measured run down one reach of one ditch."""

    ditch: DitchCode
    run_on: date
    from_station_feet: Decimal
    to_station_feet: Decimal
    inflow_cfs: Decimal
    outflow_cfs: Decimal
    turnouts_running_cfs: Decimal = Decimal("0")
    flume_error_cfs: Decimal = DEFAULT_FLUME_ERROR
    note: str = ""

    def __post_init__(self) -> None:
        if self.to_station_feet <= self.from_station_feet:
            raise ValidationError(
                f"the run on {self.ditch} ends at station {self.to_station_feet}, which is "
                f"not below {self.from_station_feet}"
            )
        if self.inflow_cfs <= 0:
            raise ValidationError(f"the run on {self.ditch} started with no water in the ditch")
        if self.outflow_cfs < 0 or self.turnouts_running_cfs < 0:
            raise ValidationError(f"the run on {self.ditch} carries a negative flow")
        if self.flume_error_cfs < 0:
            raise ValidationError("a measurement error may not be negative")

    @property
    def length_feet(self) -> Decimal:
        return self.to_station_feet - self.from_station_feet

    @property
    def length_miles(self) -> Decimal:
        return self.length_feet / FEET_PER_MILE

    @property
    def loss_cfs(self) -> Decimal:
        return round_rate(self.inflow_cfs - self.outflow_cfs - self.turnouts_running_cfs)

    @property
    def is_gaining(self) -> bool:
        return self.loss_cfs < 0

    @property
    def error_band_cfs(self) -> Decimal:
        """What the two flumes together could be wrong by."""

        return round_rate(self.flume_error_cfs * 2)

    @property
    def is_measurable(self) -> bool:
        return abs(self.loss_cfs) > self.error_band_cfs

    @property
    def turnouts_were_shut(self) -> bool:
        return self.turnouts_running_cfs == 0

    @property
    def is_long_enough(self) -> bool:
        return self.length_feet >= MINIMUM_REACH_FEET

    @property
    def is_credible(self) -> bool:
        return self.is_measurable and self.turnouts_were_shut and self.is_long_enough

    @property
    def loss_fraction_per_mile(self) -> Decimal:
        """What the run says the ditch loses, as a share of the flow a mile."""

        if self.length_miles <= 0:
            raise PolicyError(f"the run on {self.ditch} covers no distance")
        return (self.loss_cfs / self.inflow_cfs / self.length_miles).quantize(Decimal("0.0001"))

    def why_not(self) -> tuple[str, ...]:
        """Everything wrong with the run, for the file it goes in."""

        found: list[str] = []
        if not self.turnouts_were_shut:
            found.append(f"{self.turnouts_running_cfs} cfs was running to turnouts during the run")
        if not self.is_measurable:
            found.append(
                f"the loss of {self.loss_cfs} cfs is inside the {self.error_band_cfs} cfs "
                "the flumes could be wrong by"
            )
        if not self.is_long_enough:
            found.append(f"{self.length_feet} feet is too short a reach to measure over")
        return tuple(found)


@dataclass(frozen=True, slots=True)
class SeepageHistory:
    """Every run on one ditch, oldest first."""

    ditch: DitchCode
    runs: tuple[SeepageRun, ...] = ()

    def __post_init__(self) -> None:
        for run in self.runs:
            if run.ditch != self.ditch:
                raise ValidationError(
                    f"a run on {run.ditch} turned up in the history for {self.ditch}"
                )
        days = [run.run_on for run in self.runs]
        if days != sorted(days):
            raise ValidationError(f"the runs on {self.ditch} are out of order")

    @property
    def credible(self) -> tuple[SeepageRun, ...]:
        return tuple(run for run in self.runs if run.is_credible)

    @property
    def gaining(self) -> tuple[SeepageRun, ...]:
        return tuple(run for run in self.runs if run.is_gaining)

    def measured_loss_per_mile(self) -> Decimal:
        """The rate to use, out of the runs worth using."""

        usable = [run for run in self.credible if not run.is_gaining]
        if not usable:
            raise PolicyError(f"no run on {self.ditch} is worth setting a loss rate from")
        total = sum((run.loss_fraction_per_mile for run in usable), Decimal("0"))
        return (total / Decimal(len(usable))).quantize(Decimal("0.0001"))

    def has_got_worse(self, standing_rate: Decimal, tolerance: Decimal = Decimal("0.01")) -> bool:
        """Whether the ditch is losing more than the book says it does."""

        if tolerance < 0:
            raise ValidationError("a tolerance may not be negative")
        return self.measured_loss_per_mile() > standing_rate + tolerance

    def latest(self) -> SeepageRun:
        if not self.runs:
            raise PolicyError(f"nobody has run a seepage test on {self.ditch}")
        return self.runs[-1]
