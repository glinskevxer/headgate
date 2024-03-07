"""What the ditch rider wrote down.

A reading is evidence, not a flow. It records what the staff said, who read it
and when, and nothing in this module converts anything. That separation is
deliberate: the same reading can mean one thing while the device is calibrated
and something weaker afterwards, and the record on paper does not change when
the calibration lapses.

Readings for one device are kept in a series, in time order, because a volume
comes from the pair of readings that bracket a span and not from either alone.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime
from decimal import Decimal
from enum import Enum

from ..errors import ConflictError, NotFoundError, ValidationError
from ..ids import DeviceTag
from ..wateryear import Span


class ReadingMethod(Enum):
    """How the number in the book was arrived at."""

    STAFF = "staff"
    RECORDER = "recorder"
    METER_TOTAL = "meter_total"
    VISUAL = "visual"

    @property
    def is_instrument(self) -> bool:
        return self is not ReadingMethod.VISUAL


@dataclass(frozen=True, slots=True)
class StaffReading:
    """One trip to one device."""

    device: DeviceTag
    taken_at: datetime
    observer: str
    method: ReadingMethod = ReadingMethod.STAFF
    head_feet: Decimal | None = None
    tail_feet: Decimal | None = None
    meter_total_af: Decimal | None = None
    note: str = ""

    def __post_init__(self) -> None:
        if not self.observer.strip():
            raise ValidationError(f"the reading on {self.device} says who took it, and it does not")
        if self.method is ReadingMethod.METER_TOTAL:
            if self.meter_total_af is None:
                raise ValidationError(f"the meter reading on {self.device} carries no total")
            if self.head_feet is not None:
                raise ValidationError(f"the meter reading on {self.device} also carries a head")
        else:
            if self.head_feet is None:
                raise ValidationError(f"the reading on {self.device} carries no head")
            if self.meter_total_af is not None:
                raise ValidationError(f"the staff reading on {self.device} carries a meter total")
        if self.head_feet is not None and self.head_feet < 0:
            raise ValidationError(f"a head of {self.head_feet} feet is below the sill")
        if self.tail_feet is not None and self.tail_feet < 0:
            raise ValidationError(f"a tailwater of {self.tail_feet} feet is below the sill")
        if self.meter_total_af is not None and self.meter_total_af < 0:
            raise ValidationError("a meter total runs forward, not backward")

    @property
    def has_tailwater(self) -> bool:
        return self.tail_feet is not None

    @property
    def head(self) -> Decimal:
        if self.head_feet is None:
            raise ValidationError(f"the reading on {self.device} has no head to read")
        return self.head_feet


@dataclass(frozen=True, slots=True)
class ReadingSeries:
    """Every reading on one device, oldest first."""

    device: DeviceTag
    readings: tuple[StaffReading, ...] = ()

    def __post_init__(self) -> None:
        seen: set[datetime] = set()
        for reading in self.readings:
            if reading.device != self.device:
                raise ValidationError(
                    f"a reading on {reading.device} does not belong in the series for {self.device}"
                )
            if reading.taken_at in seen:
                raise ValidationError(
                    f"device {self.device} has two readings at {reading.taken_at}"
                )
            seen.add(reading.taken_at)
        for earlier, later in zip(self.readings, self.readings[1:], strict=False):
            if later.taken_at < earlier.taken_at:
                raise ValidationError(f"the series for {self.device} is out of time order")

    def add(self, reading: StaffReading) -> ReadingSeries:
        if reading.device != self.device:
            raise ValidationError(f"reading on {reading.device} is not for {self.device}")
        if any(item.taken_at == reading.taken_at for item in self.readings):
            raise ConflictError(f"device {self.device} was already read at {reading.taken_at}")
        ordered = tuple(sorted((*self.readings, reading), key=lambda item: item.taken_at))
        return replace(self, readings=ordered)

    def between(self, span: Span) -> tuple[StaffReading, ...]:
        return tuple(item for item in self.readings if span.contains(item.taken_at))

    def latest_at_or_before(self, moment: datetime) -> StaffReading:
        found: StaffReading | None = None
        for reading in self.readings:
            if reading.taken_at <= moment:
                found = reading
        if found is None:
            raise NotFoundError("reading", f"{self.device} at or before {moment}")
        return found

    def first_after(self, moment: datetime) -> StaffReading:
        for reading in self.readings:
            if reading.taken_at > moment:
                return reading
        raise NotFoundError("reading", f"{self.device} after {moment}")

    def bracketing(self, span: Span) -> tuple[StaffReading, ...]:
        """The readings needed to account for a span, ends included."""

        inside = self.between(span)
        opening = self.latest_at_or_before(span.start)
        readings = [opening, *[item for item in inside if item.taken_at != opening.taken_at]]
        return tuple(readings)

    @property
    def is_empty(self) -> bool:
        return not self.readings
