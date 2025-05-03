"""The exception report: what needs somebody's attention this week.

Nobody reads a report that lists everything. This lists only what is wrong, in
the order it costs the district money, and it is built to be run every Monday
and to print nothing at all in a good week.

The ordering is the argument. A turnout nobody is measuring costs the district
every acre foot that goes through it. A calibration about to lapse costs
nothing today and turns a measured season into an estimated one the moment it
does. An account over its allotment is a conversation. A lapsed calibration
that has already cost a season is a restatement.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from enum import Enum

from ..errors import ValidationError
from ..measure.delivery import DeliveryLedger
from ..model.device import Device

DEFAULT_LOOKAHEAD_DAYS = 30


class Urgency(Enum):
    """How soon somebody has to do something about it."""

    NOW = "now"
    THIS_WEEK = "this week"
    BEFORE_THE_SEASON = "before the season"

    @property
    def rank(self) -> int:
        return {Urgency.NOW: 0, Urgency.THIS_WEEK: 1, Urgency.BEFORE_THE_SEASON: 2}[self]


@dataclass(frozen=True, slots=True)
class Attention:
    """One thing that wants doing."""

    urgency: Urgency
    subject: str
    detail: str
    costs_water: bool = False

    def describe(self) -> str:
        return f"{self.urgency.value}: {self.subject}: {self.detail}"


def unmeasured_turnouts(ledger: DeliveryLedger) -> tuple[Attention, ...]:
    """Turnouts with no record at all, which is water nobody can bill for.

    A turnout with a hole in the middle of its record is a different problem
    and it is reported as a gap. This is the one where nobody measured
    anything: no device, or a device that was out of the ditch all season.
    """

    return tuple(
        Attention(
            urgency=Urgency.NOW,
            subject=str(record.turnout),
            detail="nothing was measured at this turnout all season",
            costs_water=True,
        )
        for record in ledger.records
        if record.total_af == 0
    )


def estimated_turnouts(
    ledger: DeliveryLedger, share_floor: Decimal = Decimal("0.25")
) -> tuple[Attention, ...]:
    """Turnouts where most of the season is an estimate rather than a record."""

    if share_floor < 0 or share_floor > 1:
        raise ValidationError(f"{share_floor} is not a share of a season")
    found: list[Attention] = []
    for record in ledger.records:
        if record.total_af <= 0 or not record.provenance.has_a_rate:
            continue
        share = record.estimated_af / record.total_af
        if share > share_floor:
            found.append(
                Attention(
                    urgency=Urgency.THIS_WEEK,
                    subject=str(record.turnout),
                    detail=f"{(share * 100).quantize(Decimal('0.1'))} percent of this season "
                    "is estimated",
                    costs_water=True,
                )
            )
    return tuple(found)


def calibrations_running_out(
    devices: tuple[Device, ...], on: date, lookahead_days: int = DEFAULT_LOOKAHEAD_DAYS
) -> tuple[Attention, ...]:
    """Checks that lapse soon, which is the cheapest thing on this list to fix."""

    if lookahead_days < 0:
        raise ValidationError("a lookahead may not run backwards")
    horizon = on + timedelta(days=lookahead_days)
    found: list[Attention] = []
    for device in devices:
        if not device.in_service_on(on):
            continue
        standing = device.calibration_on(on)
        if standing is None:
            found.append(
                Attention(
                    urgency=Urgency.NOW,
                    subject=str(device.tag),
                    detail="no calibration stands on this device",
                    costs_water=True,
                )
            )
        elif standing.expires <= horizon:
            found.append(
                Attention(
                    urgency=Urgency.THIS_WEEK,
                    subject=str(device.tag),
                    detail=f"the calibration lapses {standing.expires}",
                )
            )
    return tuple(found)


def gaps_in_the_record(
    ledger: DeliveryLedger, hours_floor: Decimal = Decimal("48")
) -> tuple[Attention, ...]:
    """Turnouts with a long stretch nobody read."""

    if hours_floor < 0:
        raise ValidationError("an hours floor may not be negative")
    return tuple(
        Attention(
            urgency=Urgency.THIS_WEEK,
            subject=str(record.turnout),
            detail=f"{record.unaccounted_hours} hours of this season are unaccounted for",
            costs_water=True,
        )
        for record in ledger.records
        if record.unaccounted_hours > hours_floor and record.total_af > 0
    )


@dataclass(frozen=True, slots=True)
class ExceptionReport:
    """Everything wanting attention, worst first."""

    on: date
    exceptions: tuple[Attention, ...]

    @property
    def is_quiet(self) -> bool:
        return not self.exceptions

    @property
    def costing_water(self) -> tuple[Attention, ...]:
        return tuple(item for item in self.exceptions if item.costs_water)

    @property
    def now(self) -> tuple[Attention, ...]:
        return tuple(item for item in self.exceptions if item.urgency is Urgency.NOW)

    def rows(self) -> list[list[str]]:
        return [
            [item.urgency.value, item.subject, item.detail, "yes" if item.costs_water else "no"]
            for item in self.exceptions
        ]


def build(
    on: date,
    ledger: DeliveryLedger,
    devices: tuple[Device, ...],
    lookahead_days: int = DEFAULT_LOOKAHEAD_DAYS,
) -> ExceptionReport:
    """Put the week's list together, worst first."""

    found = [
        *unmeasured_turnouts(ledger),
        *calibrations_running_out(devices, on, lookahead_days),
        *estimated_turnouts(ledger),
        *gaps_in_the_record(ledger),
    ]
    ordered = sorted(found, key=lambda item: (item.urgency.rank, item.subject))
    return ExceptionReport(on=on, exceptions=tuple(ordered))
