"""How long water takes to get there, and how much of it arrives.

Shutting a headgate does not put water in front of a senior right. It puts
water in the stream, at that point, at that moment, and the stream then takes
hours to carry it down and keeps some of it on the way. Both of those are
properties of the reaches between the two diversions, and both of them decide
whether a call is worth issuing at all.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal

from ..errors import ValidationError
from ..model.stream import Stream
from ..units import round_rate

SECONDS_PER_MINUTE = Decimal("60")


@dataclass(frozen=True, slots=True)
class Delivery:
    """Water let go at one point, and what shows up at another."""

    released_cfs: Decimal
    released_at: datetime
    arrives_at: datetime
    arriving_cfs: Decimal
    travel_seconds: Decimal
    carried_fraction: Decimal

    @property
    def lost_cfs(self) -> Decimal:
        return round_rate(self.released_cfs - self.arriving_cfs)

    @property
    def travel_hours(self) -> Decimal:
        return (self.travel_seconds / Decimal("3600")).quantize(Decimal("0.01"))

    @property
    def arrives_the_same_day(self) -> bool:
        return self.arrives_at.date() == self.released_at.date()


def travel_seconds(stream: Stream, upper_mile: Decimal, lower_mile: Decimal) -> Decimal:
    """Seconds for water to run between two points, rounded to the minute."""

    seconds = stream.travel_seconds(upper_mile, lower_mile)
    minutes = (seconds / SECONDS_PER_MINUTE).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    return minutes * SECONDS_PER_MINUTE


def arrival_of(
    stream: Stream, upper_mile: Decimal, lower_mile: Decimal, released_at: datetime
) -> datetime:
    """When water let go upstream reaches a point downstream."""

    seconds = travel_seconds(stream, upper_mile, lower_mile)
    return released_at + timedelta(seconds=float(seconds))


def carried(stream: Stream, upper_mile: Decimal, lower_mile: Decimal, cfs: Decimal) -> Decimal:
    """The part of a released flow that survives the reaches in between."""

    if cfs < 0:
        raise ValidationError("a release may not be negative")
    return round_rate(cfs * stream.carried_fraction(upper_mile, lower_mile))


def release(
    stream: Stream,
    upper_mile: Decimal,
    lower_mile: Decimal,
    cfs: Decimal,
    released_at: datetime,
) -> Delivery:
    """Everything about letting a flow go at one point for another."""

    seconds = travel_seconds(stream, upper_mile, lower_mile)
    fraction = stream.carried_fraction(upper_mile, lower_mile)
    return Delivery(
        released_cfs=round_rate(cfs),
        released_at=released_at,
        arrives_at=released_at + timedelta(seconds=float(seconds)),
        arriving_cfs=carried(stream, upper_mile, lower_mile, cfs),
        travel_seconds=seconds,
        carried_fraction=fraction,
    )


def release_needed_for(
    stream: Stream, upper_mile: Decimal, lower_mile: Decimal, wanted_cfs: Decimal
) -> Decimal:
    """How much has to be let go upstream to land a flow downstream."""

    if wanted_cfs < 0:
        raise ValidationError("a delivery may not be negative")
    fraction = stream.carried_fraction(upper_mile, lower_mile)
    if fraction <= 0:
        raise ValidationError("the reach loses everything, so nothing can be delivered through it")
    return round_rate(wanted_cfs / fraction)


def reaches_in_time(
    stream: Stream,
    upper_mile: Decimal,
    lower_mile: Decimal,
    released_at: datetime,
    needed_by: datetime,
) -> bool:
    """Whether water let go now is there before it stops being any use."""

    if needed_by < released_at:
        raise ValidationError("water cannot be needed before it was let go")
    return arrival_of(stream, upper_mile, lower_mile, released_at) <= needed_by
