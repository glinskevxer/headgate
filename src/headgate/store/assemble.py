"""Building the season's picture out of the book.

The domain code takes devices, readings and spans. The book holds rows. This is
the layer that turns one into the other, and it is deliberately the only place
that knows both, so neither the domain nor the repositories have to.

A turnout with no device in it is not an error and it is not nothing either. It
gets a record with no reading behind it, which comes out void, so the season
report shows the gap instead of quietly leaving the turnout off.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from ..carriage.apportion import Apportionment, LossPolicy, apportion, measured_loss
from ..duty.hcu import SeasonRecord
from ..errors import NotFoundError, PolicyError
from ..ids import AccountNumber, DeviceTag, DitchCode, TurnoutCode
from ..measure.delivery import DeliveryLedger, DeliveryRecord, record_for
from ..measure.integrate import (
    DEFAULT_STALE_AFTER_HOURS,
    IntegratedVolume,
    Integration,
    VolumeSegment,
    integrate,
)
from ..measure.quality import Provenance
from ..model.ditch import DitchSystem
from ..model.reading import ReadingSeries
from ..wateryear import IrrigationSeason, Span
from .repo_accounts import load_place_of_use, load_register
from .repo_devices import device_at_turnout, load_devices
from .repo_ditch import load_system
from .repo_readings import load_series_within
from .repo_season import load_season


def _nothing_measured(turnout: TurnoutCode, span: Span, why: str) -> DeliveryRecord:
    return DeliveryRecord(
        turnout=turnout,
        device=DeviceTag("METER-MAIN"),
        volume=IntegratedVolume(
            span=span,
            segments=(VolumeSegment(span, Decimal("0"), Decimal("0"), Provenance.VOID, why),),
        ),
    )


def build_ledger(
    connection: sqlite3.Connection,
    span: Span,
    method: Integration = Integration.STEP,
    stale_after_hours: Decimal | None = DEFAULT_STALE_AFTER_HOURS,
) -> DeliveryLedger:
    """One record for every turnout on the system over a span."""

    system = load_system(connection)
    records: list[DeliveryRecord] = []
    for turnout in system.all_turnouts():
        try:
            device = device_at_turnout(connection, turnout.code, span.start.date())
        except NotFoundError:
            records.append(_nothing_measured(turnout.code, span, "no device was in the turnout"))
            continue
        series = load_series_within(connection, device.tag, span)
        records.append(record_for(turnout.code, device, series, span, method, stale_after_hours))
    return DeliveryLedger(span=span, records=tuple(records))


def headgate_volume(
    connection: sqlite3.Connection,
    span: Span,
    ditch: DitchCode | None = None,
    method: Integration = Integration.STEP,
) -> IntegratedVolume:
    """What the main canal's own device says came through the headgate."""

    system = load_system(connection)
    code = ditch if ditch is not None else system.main.code
    devices = [item for item in load_devices(connection) if item.ditch == code]
    in_service = [item for item in devices if item.in_service_on(span.start.date())]
    if not in_service:
        raise PolicyError(f"ditch {code} has no device on it to measure the headgate")
    if len(in_service) > 1:
        raise PolicyError(
            f"ditch {code} has {len(in_service)} devices on it and the headgate is one number"
        )
    device = in_service[0]
    series = load_series_within(connection, device.tag, span)
    return integrate(device, series, span, method)


def series_for_turnout(
    connection: sqlite3.Connection, turnout: TurnoutCode, span: Span
) -> ReadingSeries:
    """The readings behind one turnout's record, for somebody checking it."""

    device = device_at_turnout(connection, turnout, span.start.date())
    return load_series_within(connection, device.tag, span)


def turnouts_without_a_device(
    connection: sqlite3.Connection, span: Span
) -> tuple[TurnoutCode, ...]:
    """Every turnout on the system that nothing is measuring."""

    system = load_system(connection)
    missing: list[TurnoutCode] = []
    for turnout in system.all_turnouts():
        try:
            device_at_turnout(connection, turnout.code, span.start.date())
        except NotFoundError:
            missing.append(turnout.code)
    return tuple(missing)


def turnout_owners(
    connection: sqlite3.Connection, on: date
) -> dict[TurnoutCode, dict[AccountNumber, Decimal]]:
    """The shares each account held at each turnout on a day.

    A turnout with two shareholders behind it comes back with both of them and
    what each holds, which is what the season close splits the water on.
    """

    register = load_register(connection)
    found: dict[TurnoutCode, dict[AccountNumber, Decimal]] = {}
    for certificate in register.held_on(on):
        gate = found.setdefault(certificate.turnout, {})
        gate[certificate.account] = gate.get(certificate.account, Decimal("0")) + (
            certificate.shares
        )
    return found


def shares_by_account(connection: sqlite3.Connection, on: date) -> dict[AccountNumber, Decimal]:
    """What every account held on a day, including the ones holding nothing."""

    register = load_register(connection)
    return {holder.number: register.shares_of(holder.number, on) for holder in register.accounts}


def shares_by_turnout(connection: sqlite3.Connection, on: date) -> dict[TurnoutCode, Decimal]:
    """What every turnout carried on a day, for a loss split by share."""

    register = load_register(connection)
    found: dict[TurnoutCode, Decimal] = {}
    for certificate in register.held_on(on):
        found[certificate.turnout] = (
            found.get(certificate.turnout, Decimal("0")) + certificate.shares
        )
    return found


def consumptive_use_records(
    connection: sqlite3.Connection, turnout: TurnoutCode, water_years: Sequence[int]
) -> list[SeasonRecord]:
    """Build a consumptive use study period out of the delivery record.

    One record a year, carrying what the turnout was delivered, how well that
    is known, and the ground and crop behind it. The provenance is the part
    that decides the answer: a year the record is only estimated is a year the
    study cannot count, and that comes straight off the ledger rather than out
    of anybody's judgement.
    """

    found: list[SeasonRecord] = []
    for water_year in sorted(set(water_years)):
        try:
            season = load_season(connection, water_year)
        except NotFoundError:
            continue
        ledger = build_ledger(connection, season.as_span())
        try:
            record = ledger.for_turnout(turnout)
        except PolicyError:
            continue
        place = load_place_of_use(connection)
        parcels = [
            parcel
            for parcel in place.parcels
            if parcel.turnout == turnout and parcel.in_production_on(season.opened)
        ]
        if not parcels:
            continue
        acres = sum((parcel.irrigated_acres for parcel in parcels), Decimal("0"))
        biggest = max(parcels, key=lambda item: item.irrigated_acres)
        found.append(
            SeasonRecord(
                water_year=water_year,
                delivered_af=record.total_af,
                provenance=record.provenance,
                irrigated_acres=acres,
                crop=biggest.crop,
                application=biggest.application,
            )
        )
    return found


@dataclass(frozen=True, slots=True)
class SeasonPicture:
    """A season as every report needs it, assembled once.

    Four of the reports opened the season, built the ledger, read the headgate
    and charged the loss out in the same four lines, which is four places for
    the loss rule to drift apart. It is assembled here instead.
    """

    season: IrrigationSeason
    ledger: DeliveryLedger
    headgate: IntegratedVolume
    apportionment: Apportionment
    system: DitchSystem

    @property
    def span(self) -> Span:
        return self.season.as_span()

    @property
    def volumes(self) -> dict[TurnoutCode, Decimal]:
        return self.ledger.volumes()

    @property
    def loss_af(self) -> Decimal:
        return measured_loss(self.headgate.total_af, self.volumes)


def season_picture(
    connection: sqlite3.Connection,
    water_year: int,
    policy: LossPolicy = LossPolicy.BY_LEG,
    method: Integration = Integration.STEP,
) -> SeasonPicture:
    """Open a season and work everything the reports read off it."""

    season = load_season(connection, water_year)
    span = season.as_span()
    ledger = build_ledger(connection, span, method)
    headgate = headgate_volume(connection, span, method=method)
    system = load_system(connection)
    volumes = ledger.volumes()
    shares = shares_by_turnout(connection, season.opened) if policy.needs_shares else None
    split = apportion(
        volumes,
        measured_loss(headgate.total_af, volumes),
        policy,
        system=system,
        shares=shares,
    )
    return SeasonPicture(
        season=season,
        ledger=ledger,
        headgate=headgate,
        apportionment=split,
        system=system,
    )
