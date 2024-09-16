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
from decimal import Decimal

from ..errors import NotFoundError, PolicyError
from ..ids import DeviceTag, DitchCode, TurnoutCode
from ..measure.delivery import DeliveryLedger, DeliveryRecord, record_for
from ..measure.integrate import IntegratedVolume, Integration, VolumeSegment, integrate
from ..measure.quality import Provenance
from ..model.reading import ReadingSeries
from ..wateryear import Span
from .repo_devices import device_at_turnout, load_devices
from .repo_ditch import load_system
from .repo_readings import load_series_within


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
        records.append(record_for(turnout.code, device, series, span, method))
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
