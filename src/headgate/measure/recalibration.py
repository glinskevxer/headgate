"""Re-rating a device backwards, and what that does to the season.

The field check in September says the staff has been reading two hundredths
high since spring. Everything that turnout delivered was over stated, and the
question is by how much and whose bill it changes.

Two rules keep this honest.

A re-rating only reaches back over the period the faulty check covered. The
season before it was measured against a different check, which either stood or
did not on its own evidence, and reaching past it would restate a year nobody
found anything wrong with.

And the old record is never overwritten. What comes out of here is the pair,
what the book said and what it should have said, with the difference between
them, because a restatement has to show its working.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import date
from decimal import Decimal

from ..errors import PolicyError, ValidationError
from ..ids import TurnoutCode
from ..model.device import Calibration, Device
from ..model.reading import ReadingSeries
from ..units import round_volume
from ..wateryear import Span
from .delivery import DeliveryRecord, record_for
from .integrate import Integration


@dataclass(frozen=True, slots=True)
class Rerating:
    """A corrected staff offset, and the days it reaches back over."""

    device: Device
    corrected_offset_feet: Decimal
    found_on: date
    found_by: str
    reason: str

    def __post_init__(self) -> None:
        if not self.found_by.strip():
            raise ValidationError("a re-rating says who found it")
        if not self.reason.strip():
            raise ValidationError("a re-rating says what was wrong")
        if abs(self.corrected_offset_feet) > Decimal("0.5"):
            raise ValidationError(
                f"an offset of {self.corrected_offset_feet} feet means the staff was reset"
            )

    @property
    def standing_check(self) -> Calibration:
        found = self.device.calibration_on(self.found_on)
        if found is None:
            raise PolicyError(
                f"device {self.device.tag} had no calibration standing on {self.found_on}, "
                "so there is nothing to re-rate"
            )
        return found

    @property
    def reaches_back_to(self) -> date:
        return self.standing_check.performed

    @property
    def offset_change(self) -> Decimal:
        return self.corrected_offset_feet - self.standing_check.staff_offset_feet

    @property
    def changes_anything(self) -> bool:
        return self.offset_change != 0

    def corrected_device(self) -> Device:
        """The device as it should have been read over that period."""

        check = self.standing_check
        corrected = replace(check, staff_offset_feet=self.corrected_offset_feet)
        others = tuple(
            item for item in self.device.calibrations if item.performed != check.performed
        )
        return replace(
            self.device,
            calibrations=tuple(sorted((*others, corrected), key=lambda item: item.performed)),
        )

    def covers(self, span: Span) -> bool:
        check = self.standing_check
        return span.start.date() >= check.performed and span.end.date() <= check.expires


@dataclass(frozen=True, slots=True)
class Restated:
    """What the record said, what it should say, and the difference."""

    turnout: TurnoutCode
    before: DeliveryRecord
    after: DeliveryRecord
    rerating: Rerating

    @property
    def change_af(self) -> Decimal:
        return round_volume(self.after.total_af - self.before.total_af)

    @property
    def is_a_credit(self) -> bool:
        return self.change_af < 0

    @property
    def percent_change(self) -> Decimal:
        if self.before.total_af == 0:
            return Decimal("0")
        return (self.change_af / self.before.total_af * 100).quantize(Decimal("0.1"))

    def describe(self) -> str:
        direction = "less" if self.is_a_credit else "more"
        return (
            f"{self.turnout} delivered {abs(self.change_af)} acre feet {direction} than the "
            f"book says, {self.percent_change} percent, because {self.rerating.reason}"
        )


def restate(
    rerating: Rerating,
    turnout: TurnoutCode,
    series: ReadingSeries,
    span: Span,
    method: Integration = Integration.STEP,
) -> Restated:
    """Work out what a turnout should have been credited with."""

    if not rerating.covers(span):
        check = rerating.standing_check
        raise PolicyError(
            f"the check performed {check.performed} covers to {check.expires} and the span "
            f"runs {span.start.date()} to {span.end.date()}"
        )
    before = record_for(turnout, rerating.device, series, span, method)
    after = record_for(turnout, rerating.corrected_device(), series, span, method)
    return Restated(turnout=turnout, before=before, after=after, rerating=rerating)


def material(restated: Restated, threshold_af: Decimal = Decimal("1")) -> bool:
    """Whether the change is worth restating a season over."""

    if threshold_af < 0:
        raise ValidationError("a threshold may not be negative")
    return abs(restated.change_af) >= threshold_af
