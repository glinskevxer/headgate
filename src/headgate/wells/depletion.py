"""What a well takes out of the creek, and when.

A well beside a stream does not take its water from somewhere else. It takes it
from the stream, late and spread out, and the further from the bank it sits the
later and the flatter the effect. Glover's solution puts a number on that from
three things a hydrologist can measure: how far the well is from the stream,
how much water the aquifer gives up, and how easily it moves.

Those three collapse into one number, the stream depletion factor, in days. A
well with a factor of ninety days has given the stream back most of the pumping
by the end of the season. A well at four thousand days is still depleting the
creek a decade after somebody turned the pump off, which is why the office
cares about the ones out on the bench far more than the ones by the bridge.

The arithmetic here is done in floating point on purpose. It is a physical
model with an error function in it, not an account, and pretending otherwise by
carrying it in Decimal would suggest a precision the aquifer does not have.
Volumes come in and go out as Decimal and are rounded on the way.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from decimal import Decimal

from ..errors import PolicyError, ValidationError
from ..ids import DecreeNumber
from ..units import round_volume

SECONDS_PER_DAY = Decimal("86400")


def stream_depletion_factor(
    distance_feet: Decimal, storativity: Decimal, transmissivity_ft2_day: Decimal
) -> Decimal:
    """Glover's factor in days: distance squared times storativity over T."""

    if distance_feet <= 0:
        raise ValidationError("a well in the stream is not a well, it is a diversion")
    if storativity <= 0 or storativity >= 1:
        raise ValidationError(f"a storativity of {storativity} is not an aquifer")
    if transmissivity_ft2_day <= 0:
        raise ValidationError("an aquifer that moves no water has no depletion factor")
    factor = distance_feet * distance_feet * storativity / transmissivity_ft2_day
    return factor.quantize(Decimal("0.1"))


def depletion_fraction(days: Decimal, factor_days: Decimal) -> Decimal:
    """The share of pumping that has reached the stream after so many days."""

    if days < 0:
        raise ValidationError("depletion is not worked backwards in time")
    if factor_days <= 0:
        raise ValidationError("a depletion factor of nothing is not a factor")
    if days == 0:
        return Decimal("0")
    argument = math.sqrt(float(factor_days) / (4.0 * float(days)))
    return Decimal(str(math.erfc(argument))).quantize(Decimal("0.0001"))


@dataclass(frozen=True, slots=True)
class Well:
    """One supplemental well and where it sits."""

    well_id: str
    decree: DecreeNumber
    distance_to_stream_feet: Decimal
    storativity: Decimal
    transmissivity_ft2_day: Decimal
    capacity_gpm: Decimal
    annual_limit_af: Decimal | None = None

    def __post_init__(self) -> None:
        if not self.well_id.strip():
            raise ValidationError("a well needs an identifier")
        if self.capacity_gpm <= 0:
            raise ValidationError(f"well {self.well_id} pumps nothing")
        if self.annual_limit_af is not None and self.annual_limit_af <= 0:
            raise ValidationError(f"well {self.well_id} is limited to no water at all")

    @property
    def factor_days(self) -> Decimal:
        return stream_depletion_factor(
            self.distance_to_stream_feet, self.storativity, self.transmissivity_ft2_day
        )

    @property
    def is_close_to_the_stream(self) -> bool:
        """A well the district administers as if it were a surface diversion."""

        return self.factor_days <= Decimal("30")

    def depletion_after(self, days: Decimal) -> Decimal:
        return depletion_fraction(days, self.factor_days)

    def depletion_from(self, pumped_af: Decimal, days: Decimal) -> Decimal:
        """How much of one month's pumping has reached the creek by now."""

        if pumped_af < 0:
            raise ValidationError("a well cannot pump a negative volume")
        return round_volume(pumped_af * self.depletion_after(days))

    def season_capacity_af(self, days: Decimal) -> Decimal:
        """What the pump could produce if it ran flat out for a season."""

        gallons = self.capacity_gpm * Decimal("1440") * days
        return round_volume(gallons / Decimal("325851"))


@dataclass(frozen=True, slots=True)
class PumpingRecord:
    """One month of pumping on one well."""

    well: Well
    month: int
    pumped_af: Decimal

    def __post_init__(self) -> None:
        if self.month < 1 or self.month > 12:
            raise ValidationError(f"{self.month} is not a month")
        if self.pumped_af < 0:
            raise ValidationError(f"well {self.well.well_id} pumped a negative volume")


def depletion_by_month(
    records: list[PumpingRecord], through_month: int, days_in_month: Decimal = Decimal("30.4")
) -> dict[int, Decimal]:
    """How much each month's pumping has taken out of the creek by a month.

    Every month's pumping keeps depleting after it stops, so the answer for
    August includes a share of what was pumped in May, and a well far enough
    out is still depleting from last year.
    """

    if through_month < 1 or through_month > 12:
        raise ValidationError(f"{through_month} is not a month")
    found: dict[int, Decimal] = {}
    for record in records:
        if record.month > through_month:
            continue
        elapsed = days_in_month * Decimal(through_month - record.month + 1)
        found[record.month] = record.well.depletion_from(record.pumped_af, elapsed)
    return found


def augmentation_owed(
    records: list[PumpingRecord],
    through_month: int,
    replaced_af: Decimal = Decimal("0"),
    days_in_month: Decimal = Decimal("30.4"),
) -> Decimal:
    """What has to be put back in the creek, net of what already was.

    This is the number a well owner lives or dies by in a call year. It is not
    what he pumped; it is what the creek has actually lost by now, which is
    less in June and more in September than the pumping was.
    """

    if replaced_af < 0:
        raise ValidationError("a replacement may not be negative")
    depleted = sum(depletion_by_month(records, through_month, days_in_month).values(), Decimal("0"))
    owed = depleted - replaced_af
    return round_volume(owed) if owed > 0 else Decimal("0")


def check_annual_limit(well: Well, pumped_af: Decimal) -> Decimal:
    """Refuse a year that pumped more than the decree allows."""

    if well.annual_limit_af is not None and pumped_af > well.annual_limit_af:
        raise PolicyError(
            f"well {well.well_id} pumped {round_volume(pumped_af)} acre feet against a limit "
            f"of {well.annual_limit_af}"
        )
    return round_volume(pumped_af)
