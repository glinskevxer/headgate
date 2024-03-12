"""Volumes, from a series of readings over a span.

A rider reads a turnout every few days, so the record is a handful of points
and a volume has to be built between them. Two rules are in use here. The step
rule holds the last reading until the next one, which is what the district has
always done and what the ditch riders expect to see. The trapezoid rule ramps
between the two readings and is the one an engineer asks for when the flow was
being changed on purpose.

Provenance travels with the volume. A span half of which was read on a lapsed
calibration produces a total that is estimated, and the piece that was measured
is still reported separately, because the two are used for different things.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from enum import Enum

from ..model.device import Device
from ..model.reading import ReadingSeries
from ..units import cfs_for_seconds, round_volume
from ..wateryear import Span
from .quality import Provenance, RatedReading, rate_reading, worst_of


class Integration(Enum):
    """How the flow between two readings is treated."""

    STEP = "step"
    TRAPEZOID = "trapezoid"


@dataclass(frozen=True, slots=True)
class VolumeSegment:
    """One piece of a span, at one flow, from one pair of readings."""

    span: Span
    rate_cfs: Decimal
    volume_af: Decimal
    provenance: Provenance
    reason: str


@dataclass(frozen=True, slots=True)
class IntegratedVolume:
    """What a device delivered over a span, and how well it is known."""

    span: Span
    segments: tuple[VolumeSegment, ...]

    @property
    def total_af(self) -> Decimal:
        return round_volume(sum((piece.volume_af for piece in self.segments), Decimal("0")))

    @property
    def provenance(self) -> Provenance:
        return worst_of([piece.provenance for piece in self.segments])

    @property
    def measured_af(self) -> Decimal:
        return round_volume(
            sum(
                (
                    piece.volume_af
                    for piece in self.segments
                    if piece.provenance is Provenance.MEASURED
                ),
                Decimal("0"),
            )
        )

    @property
    def estimated_af(self) -> Decimal:
        return round_volume(self.total_af - self.measured_af)

    @property
    def unaccounted_seconds(self) -> Decimal:
        return sum(
            (piece.span.seconds for piece in self.segments if piece.provenance is Provenance.VOID),
            Decimal("0"),
        )

    @property
    def mean_rate_cfs(self) -> Decimal:
        seconds = self.span.seconds
        if seconds <= 0:
            return Decimal("0")
        return (self.total_af * Decimal("43560") / seconds).quantize(Decimal("0.001"))


def _segment(
    span: Span, opening: RatedReading, closing: RatedReading | None, method: Integration
) -> VolumeSegment:
    if opening.provenance is Provenance.VOID:
        return VolumeSegment(span, Decimal("0"), Decimal("0"), Provenance.VOID, opening.reason)
    rate = opening.rate
    provenance: Provenance = opening.provenance
    reason = opening.reason
    if (
        method is Integration.TRAPEZOID
        and closing is not None
        and closing.provenance is not Provenance.VOID
    ):
        rate = ((opening.rate + closing.rate) / 2).quantize(Decimal("0.001"))
        provenance = worst_of([opening.provenance, closing.provenance])
        if closing.provenance is not Provenance.MEASURED:
            reason = f"{reason}; closing reading {closing.reason}"
    return VolumeSegment(
        span=span,
        rate_cfs=rate,
        volume_af=cfs_for_seconds(rate, span.seconds),
        provenance=provenance,
        reason=reason,
    )


def integrate(
    device: Device,
    series: ReadingSeries,
    span: Span,
    method: Integration = Integration.STEP,
) -> IntegratedVolume:
    """Build the volume a device passed over a span from its readings."""

    rated = [rate_reading(device, item) for item in series.readings]
    inside = [item for item in rated if span.contains(item.reading.taken_at)]
    before = [item for item in rated if item.reading.taken_at <= span.start]
    opening = before[-1] if before else None
    segments: list[VolumeSegment] = []
    cursor = span.start
    if opening is None:
        if not inside:
            return IntegratedVolume(
                span,
                (
                    VolumeSegment(
                        span, Decimal("0"), Decimal("0"), Provenance.VOID, "nobody read the device"
                    ),
                ),
            )
        first = inside[0].reading.taken_at
        segments.append(
            VolumeSegment(
                span=Span(cursor, first),
                rate_cfs=Decimal("0"),
                volume_af=Decimal("0"),
                provenance=Provenance.VOID,
                reason="the span opened before the first reading",
            )
        )
        cursor = first
        opening = inside[0]
        inside = inside[1:]
    for item in inside:
        moment = item.reading.taken_at
        if moment > cursor:
            segments.append(_segment(Span(cursor, moment), opening, item, method))
            cursor = moment
        opening = item
    if cursor < span.end:
        segments.append(_segment(Span(cursor, span.end), opening, None, method))
    return IntegratedVolume(span, tuple(segments))
