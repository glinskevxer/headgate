"""Runoff forecasts, and the supply a district is willing to promise.

The forecast arrives on the first of April and again on the first of May and
June, each one a set of volumes at exceedance levels: the number that will be
beaten nine years in ten, the middle number, and the number that will be beaten
only one year in ten. A district that plans on the middle number is wrong half
the time in the direction that hurts.

So the supply the board allots against is not the forecast. It is the forecast
at whatever exceedance the district has the nerve for, plus what is carried
over in the reservoir, less the water the ditch is going to lose getting it
anywhere. The three pieces are kept apart because the board argues about them
separately.

A later forecast supersedes an earlier one. Planning on the April number in
June, after the May and June numbers came in lower, is the specific mistake
this refuses to let anybody make quietly.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from enum import Enum

from ..errors import PolicyError, ValidationError
from ..units import round_volume


class Exceedance(Enum):
    """How likely the runoff is to beat a number."""

    WET = "10 percent"
    LIKELY = "30 percent"
    MEDIAN = "50 percent"
    DRY = "70 percent"
    CRITICAL = "90 percent"

    @property
    def is_conservative(self) -> bool:
        return self in {Exceedance.DRY, Exceedance.CRITICAL}


@dataclass(frozen=True, slots=True)
class Forecast:
    """One forecast, issued on one day, for one water year."""

    water_year: int
    issued_on: date
    source: str
    volumes_af: dict[Exceedance, Decimal]

    def __post_init__(self) -> None:
        if not self.source.strip():
            raise ValidationError("a forecast says who issued it")
        missing = [level for level in Exceedance if level not in self.volumes_af]
        if missing:
            raise ValidationError(
                f"the {self.water_year} forecast has no {missing[0].value} number"
            )
        if any(value < 0 for value in self.volumes_af.values()):
            raise ValidationError("a forecast may not predict a negative runoff")
        ordered = [self.volumes_af[level] for level in Exceedance]
        for higher, lower in zip(ordered, ordered[1:], strict=False):
            if lower > higher:
                raise ValidationError(
                    "a forecast that beats a wetter number at a drier exceedance is backwards"
                )

    def at(self, level: Exceedance) -> Decimal:
        return self.volumes_af[level]

    @property
    def median_af(self) -> Decimal:
        return self.at(Exceedance.MEDIAN)

    @property
    def spread_af(self) -> Decimal:
        return round_volume(self.at(Exceedance.WET) - self.at(Exceedance.CRITICAL))

    def is_dry_year(self, average_af: Decimal) -> bool:
        """A year is dry when the middle number is well under average."""

        if average_af <= 0:
            raise ValidationError("an average runoff of nothing is not an average")
        return self.median_af < average_af * Decimal("0.75")

    def percent_of_average(self, average_af: Decimal) -> Decimal:
        if average_af <= 0:
            raise ValidationError("an average runoff of nothing is not an average")
        return (self.median_af / average_af * 100).quantize(Decimal("0.1"))


@dataclass(frozen=True, slots=True)
class ForecastSeries:
    """Every forecast issued for one year, oldest first."""

    water_year: int
    forecasts: tuple[Forecast, ...] = ()

    def __post_init__(self) -> None:
        for item in self.forecasts:
            if item.water_year != self.water_year:
                raise ValidationError(
                    f"a {item.water_year} forecast turned up in the {self.water_year} series"
                )
        days = [item.issued_on for item in self.forecasts]
        if days != sorted(days):
            raise ValidationError(f"the {self.water_year} forecasts are out of order")
        if len(set(days)) != len(days):
            raise ValidationError(f"the {self.water_year} series has two forecasts one day")

    def add(self, forecast: Forecast) -> ForecastSeries:
        ordered = tuple(sorted((*self.forecasts, forecast), key=lambda item: item.issued_on))
        return ForecastSeries(water_year=self.water_year, forecasts=ordered)

    def current_on(self, day: date) -> Forecast:
        """The forecast that stood on a day, which is the latest one issued."""

        standing = [item for item in self.forecasts if item.issued_on <= day]
        if not standing:
            raise PolicyError(f"no forecast had been issued for {self.water_year} by {day}")
        return standing[-1]

    @property
    def latest(self) -> Forecast:
        if not self.forecasts:
            raise PolicyError(f"no forecast has been issued for {self.water_year}")
        return self.forecasts[-1]

    def check_current(self, forecast: Forecast, on: date) -> Forecast:
        """Refuse a forecast that has already been superseded."""

        standing = self.current_on(on)
        if standing.issued_on > forecast.issued_on:
            raise PolicyError(
                f"the {forecast.issued_on} forecast was superseded by the {standing.issued_on} one"
            )
        return forecast


@dataclass(frozen=True, slots=True)
class Supply:
    """What the board is willing to allot against, and what it is made of."""

    water_year: int
    forecast_af: Decimal
    carryover_af: Decimal
    shrink_fraction: Decimal
    basis: str

    def __post_init__(self) -> None:
        if self.forecast_af < 0 or self.carryover_af < 0:
            raise ValidationError("a supply may not be built from negative water")
        if self.shrink_fraction < 0 or self.shrink_fraction >= 1:
            raise ValidationError(f"a shrink of {self.shrink_fraction} would lose the whole supply")

    @property
    def gross_af(self) -> Decimal:
        return round_volume(self.forecast_af + self.carryover_af)

    @property
    def shrink_af(self) -> Decimal:
        return round_volume(self.gross_af * self.shrink_fraction)

    @property
    def deliverable_af(self) -> Decimal:
        return round_volume(self.gross_af - self.shrink_af)


def supply_from(
    forecast: Forecast,
    level: Exceedance,
    carryover_af: Decimal,
    shrink_fraction: Decimal,
) -> Supply:
    """Build the supply the allotment will be worked out from."""

    return Supply(
        water_year=forecast.water_year,
        forecast_af=forecast.at(level),
        carryover_af=carryover_af,
        shrink_fraction=shrink_fraction,
        basis=f"{forecast.source} {forecast.issued_on} at {level.value} exceedance",
    )
