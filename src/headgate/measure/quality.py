"""What a reading is worth once the device is taken into account.

Three answers are possible and they are not degrees of the same thing.

A measured reading was taken on a calibrated device inside its rated range. It
is evidence, and it is the only kind that counts toward historical consumptive
use later on.

An estimated reading produced a number nobody should lean on: the calibration
had lapsed, or the staff was read past the end of the rating, or the rider
eyeballed it. The delivery still happened and the account still gets billed for
it. It is simply not proof of anything.

A void reading produced no number at all. The device was out of the ditch, or
the flume was drowned, and there is nothing to convert.

The order matters. A drowned flume read by an uncalibrated rider is void, not
estimated, because there is no flow to weaken confidence in.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from enum import Enum

from ..errors import HeadOutOfRangeError, PolicyError, SubmergedFlowError
from ..model.device import Device, DeviceKind
from ..model.reading import ReadingMethod, StaffReading
from ..rating.flume import CutthroatFlume, ParshallFlume
from ..rating.select import rating_for


class Provenance(Enum):
    """How much weight the record carries."""

    MEASURED = "measured"
    ESTIMATED = "estimated"
    VOID = "void"

    @property
    def counts_as_evidence(self) -> bool:
        return self is Provenance.MEASURED

    @property
    def has_a_rate(self) -> bool:
        return self is not Provenance.VOID


def worst_of(provenances: list[Provenance]) -> Provenance:
    """The weakest provenance in a set, which is what a total inherits."""

    if not provenances:
        return Provenance.VOID
    if any(item is Provenance.VOID for item in provenances):
        return Provenance.VOID
    if any(item is Provenance.ESTIMATED for item in provenances):
        return Provenance.ESTIMATED
    return Provenance.MEASURED


@dataclass(frozen=True, slots=True)
class RatedReading:
    """A reading, the flow it means, and why it means only that much."""

    reading: StaffReading
    provenance: Provenance
    rate_cfs: Decimal | None
    reason: str

    @property
    def rate(self) -> Decimal:
        return self.rate_cfs if self.rate_cfs is not None else Decimal("0")


def _clamped(curve_low: Decimal, curve_high: Decimal, head: Decimal) -> Decimal:
    if head < curve_low:
        return curve_low
    if head > curve_high:
        return curve_high
    return head


def rate_reading(device: Device, reading: StaffReading) -> RatedReading:
    """Convert one reading against the device that produced it."""

    if reading.device != device.tag:
        raise PolicyError(f"reading on {reading.device} rated against device {device.tag}")
    day = reading.taken_at.date()
    if not device.in_service_on(day):
        return RatedReading(reading, Provenance.VOID, None, "the device was not in the ditch")
    if reading.method is ReadingMethod.METER_TOTAL:
        return RatedReading(
            reading, Provenance.VOID, None, "a meter total is a volume and not a rate"
        )
    curve = rating_for(device, day)
    head = reading.head
    if isinstance(curve, ParshallFlume | CutthroatFlume) and reading.tail_feet is not None:
        limit = curve.submergence_limit
        ratio = (reading.tail_feet / head).quantize(Decimal("0.001")) if head > 0 else limit
        if ratio > limit:
            return RatedReading(
                reading,
                Provenance.VOID,
                None,
                f"the flume was submerged at {ratio} against a limit of {limit}",
            )
    reasons: list[str] = []
    rated_head = head
    if not curve.min_head_feet <= head <= curve.max_head_feet:
        rated_head = _clamped(curve.min_head_feet, curve.max_head_feet, head)
        reasons.append(
            f"the staff read {head} ft against a rating good from "
            f"{curve.min_head_feet} to {curve.max_head_feet} ft"
        )
    if not device.is_calibrated_on(day):
        reasons.append("the calibration had lapsed")
    if not reading.method.is_instrument:
        reasons.append("the flow was eyeballed rather than read")
    try:
        rate = curve.discharge_cfs(rated_head)
    except (HeadOutOfRangeError, SubmergedFlowError) as exc:
        return RatedReading(reading, Provenance.VOID, None, str(exc))
    if reasons:
        return RatedReading(reading, Provenance.ESTIMATED, rate, "; ".join(reasons))
    return RatedReading(reading, Provenance.MEASURED, rate, "read on a calibrated device in range")


def is_totaliser(device: Device) -> bool:
    """A meter is read as a volume, so it never goes through a rating."""

    return device.kind is DeviceKind.PROPELLER_METER
