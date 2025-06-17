"""Readings that arrive from a datalogger instead of from a rider.

A pressure transducer in a stilling well reports every fifteen minutes whether
anybody wants it to or not. Three things go wrong with that and all three have
to be handled before the numbers are allowed into the delivery record.

It spikes. A gauge that jumps two feet in ten minutes did not measure a flood,
it measured a wasp landing on the transducer or the battery browning out, and
the physical rate a ditch can rise puts a limit on what is believable.

It flatlines. A stuck sensor reports the same number for three days, which
looks like the steadiest set anybody ever ran and is a dead instrument.

And there is far too much of it. Ninety six samples a day for a season is not a
record anybody reads, so what goes into the book is thinned to the interval the
district actually accounts on, and the raw samples stay in the logger.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal

from ..errors import PolicyError, ValidationError
from ..ids import DeviceTag
from ..model.reading import ReadingMethod, StaffReading

DEFAULT_RISE_LIMIT_FEET_PER_HOUR = Decimal("1.5")
DEFAULT_FLATLINE_HOURS = Decimal("48")
DEFAULT_THINNING_HOURS = Decimal("6")
LOW_BATTERY_VOLTS = Decimal("11.5")


@dataclass(frozen=True, slots=True)
class Sample:
    """One reading off the logger."""

    device: DeviceTag
    taken_at: datetime
    head_feet: Decimal
    battery_volts: Decimal | None = None

    def __post_init__(self) -> None:
        if self.head_feet < 0:
            raise ValidationError(f"{self.device} reported {self.head_feet} feet")
        if self.battery_volts is not None and self.battery_volts < 0:
            raise ValidationError(f"{self.device} reported a negative battery voltage")

    @property
    def battery_is_low(self) -> bool:
        return self.battery_volts is not None and self.battery_volts < LOW_BATTERY_VOLTS


def rate_of_change(first: Sample, second: Sample) -> Decimal:
    """Feet an hour between two samples, however far apart they are."""

    hours = Decimal(str((second.taken_at - first.taken_at).total_seconds())) / Decimal("3600")
    if hours <= 0:
        raise PolicyError(
            f"{second.device} reported two samples at {second.taken_at} or out of order"
        )
    return abs((second.head_feet - first.head_feet) / hours).quantize(Decimal("0.001"))


def is_spike(
    first: Sample, second: Sample, limit: Decimal = DEFAULT_RISE_LIMIT_FEET_PER_HOUR
) -> bool:
    if limit <= 0:
        raise ValidationError("a rise limit of nothing rejects every sample")
    return rate_of_change(first, second) > limit


@dataclass(frozen=True, slots=True)
class SampleRun:
    """Everything one logger sent for one device, in time order."""

    device: DeviceTag
    samples: tuple[Sample, ...]

    def __post_init__(self) -> None:
        for sample in self.samples:
            if sample.device != self.device:
                raise ValidationError(
                    f"a sample from {sample.device} turned up in the run for {self.device}"
                )
        moments = [sample.taken_at for sample in self.samples]
        if moments != sorted(moments):
            raise ValidationError(f"the run from {self.device} is out of time order")
        if len(set(moments)) != len(moments):
            raise ValidationError(f"the run from {self.device} repeats a moment")

    @property
    def is_empty(self) -> bool:
        return not self.samples

    def spikes(self, limit: Decimal = DEFAULT_RISE_LIMIT_FEET_PER_HOUR) -> tuple[Sample, ...]:
        found: list[Sample] = []
        for first, second in zip(self.samples, self.samples[1:], strict=False):
            if is_spike(first, second, limit):
                found.append(second)
        return tuple(found)

    def is_flatlined(self, hours: Decimal = DEFAULT_FLATLINE_HOURS) -> bool:
        """Whether the sensor has reported the same number for too long."""

        if hours <= 0:
            raise ValidationError("a flatline window of nothing catches every sensor")
        if len(self.samples) < 2:
            return False
        last = self.samples[-1]
        stuck_since = last.taken_at
        for sample in reversed(self.samples[:-1]):
            if sample.head_feet != last.head_feet:
                break
            stuck_since = sample.taken_at
        span = Decimal(str((last.taken_at - stuck_since).total_seconds())) / Decimal("3600")
        return span >= hours

    def low_battery(self) -> tuple[Sample, ...]:
        return tuple(sample for sample in self.samples if sample.battery_is_low)

    def clean(self, limit: Decimal = DEFAULT_RISE_LIMIT_FEET_PER_HOUR) -> SampleRun:
        """The run with the spikes taken out."""

        spikes = {sample.taken_at for sample in self.spikes(limit)}
        return SampleRun(
            device=self.device,
            samples=tuple(item for item in self.samples if item.taken_at not in spikes),
        )

    def thinned(self, every_hours: Decimal = DEFAULT_THINNING_HOURS) -> tuple[Sample, ...]:
        """One sample every so often, which is what the book keeps."""

        if every_hours <= 0:
            raise ValidationError("thinning to no interval keeps every sample")
        if self.is_empty:
            return ()
        kept = [self.samples[0]]
        gap = timedelta(hours=float(every_hours))
        for sample in self.samples[1:]:
            if sample.taken_at - kept[-1].taken_at >= gap:
                kept.append(sample)
        return tuple(kept)

    def readings(
        self,
        observer: str = "telemetry",
        every_hours: Decimal = DEFAULT_THINNING_HOURS,
        limit: Decimal = DEFAULT_RISE_LIMIT_FEET_PER_HOUR,
    ) -> tuple[StaffReading, ...]:
        """What the book keeps: thinned, de-spiked, marked as a recorder."""

        return tuple(
            StaffReading(
                device=sample.device,
                taken_at=sample.taken_at,
                observer=observer,
                method=ReadingMethod.RECORDER,
                head_feet=sample.head_feet,
                note="",
            )
            for sample in self.clean(limit).thinned(every_hours)
        )
