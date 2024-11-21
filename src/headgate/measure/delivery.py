"""The delivery record, which is what the whole system is for.

One record per turnout per span: what went through the gate, how much of it is
proved and how much is an estimate, and how long the record has a hole in it.
The hole matters. A turnout nobody read for eleven days in July has a volume
against it that is a guess dressed as arithmetic, and the season report says so
rather than burying it in a total.

The ledger is the season's worth of those records. It totals them, it says what
share of the district's water is only estimated, and it can hand back the piece
for one turnout so a bill can be built off it.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from ..errors import PolicyError, ValidationError
from ..ids import DeviceTag, TurnoutCode
from ..model.device import Device
from ..model.reading import ReadingSeries
from ..units import round_volume, total_volume
from ..wateryear import Span
from .integrate import DEFAULT_STALE_AFTER_HOURS, IntegratedVolume, Integration, integrate
from .quality import Provenance, worst_of


@dataclass(frozen=True, slots=True)
class DeliveryRecord:
    """What one turnout took over one span."""

    turnout: TurnoutCode
    device: DeviceTag
    volume: IntegratedVolume

    @property
    def span(self) -> Span:
        return self.volume.span

    @property
    def total_af(self) -> Decimal:
        return self.volume.total_af

    @property
    def measured_af(self) -> Decimal:
        return self.volume.measured_af

    @property
    def estimated_af(self) -> Decimal:
        return self.volume.estimated_af

    @property
    def provenance(self) -> Provenance:
        return self.volume.provenance

    @property
    def unaccounted_hours(self) -> Decimal:
        return (self.volume.unaccounted_seconds / Decimal("3600")).quantize(Decimal("0.01"))

    @property
    def is_proved(self) -> bool:
        return self.provenance.counts_as_evidence


def record_for(
    turnout: TurnoutCode,
    device: Device,
    series: ReadingSeries,
    span: Span,
    method: Integration = Integration.STEP,
    stale_after_hours: Decimal | None = DEFAULT_STALE_AFTER_HOURS,
) -> DeliveryRecord:
    """Build the record for one turnout from the device that measures it."""

    if device.turnout is not None and device.turnout != turnout:
        raise PolicyError(f"device {device.tag} measures {device.turnout}, not {turnout}")
    if series.device != device.tag:
        raise PolicyError(f"the series for {series.device} is not for device {device.tag}")
    return DeliveryRecord(
        turnout=turnout,
        device=device.tag,
        volume=integrate(device, series, span, method, stale_after_hours),
    )


@dataclass(frozen=True, slots=True)
class DeliveryLedger:
    """Every turnout's record for one span."""

    span: Span
    records: tuple[DeliveryRecord, ...]

    def __post_init__(self) -> None:
        seen: set[TurnoutCode] = set()
        for record in self.records:
            if record.turnout in seen:
                raise ValidationError(f"turnout {record.turnout} appears twice in the ledger")
            if record.span != self.span:
                raise ValidationError(
                    f"the record for {record.turnout} covers a different span from the ledger"
                )
            seen.add(record.turnout)

    @property
    def total_af(self) -> Decimal:
        return total_volume(item.total_af for item in self.records)

    @property
    def measured_af(self) -> Decimal:
        return total_volume(item.measured_af for item in self.records)

    @property
    def estimated_af(self) -> Decimal:
        return round_volume(self.total_af - self.measured_af)

    @property
    def provenance(self) -> Provenance:
        return worst_of([item.provenance for item in self.records])

    @property
    def estimated_share(self) -> Decimal:
        """How much of the season is only an estimate, as a fraction."""

        if self.total_af == 0:
            return Decimal("0")
        return (self.estimated_af / self.total_af).quantize(Decimal("0.001"))

    @property
    def turnouts(self) -> tuple[TurnoutCode, ...]:
        return tuple(sorted(item.turnout for item in self.records))

    @property
    def unproved(self) -> tuple[DeliveryRecord, ...]:
        return tuple(item for item in self.records if not item.is_proved)

    def for_turnout(self, turnout: TurnoutCode) -> DeliveryRecord:
        for item in self.records:
            if item.turnout == turnout:
                return item
        raise PolicyError(f"turnout {turnout} has no record in this ledger")

    def volumes(self) -> dict[TurnoutCode, Decimal]:
        """The totals, in the shape the loss apportionment wants them."""

        return {item.turnout: item.total_af for item in self.records}
