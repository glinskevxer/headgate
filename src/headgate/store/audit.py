"""Reading a book over and telling somebody what is wrong with it.

Districts run these books for decades and things drift. A turnout gets built
and nobody puts a device in it. A device is pulled out and the readings keep
arriving against it. A certificate is issued at a turnout that was abandoned
two years ago. None of that stops the system working, which is exactly the
problem: it stops the answers meaning anything and nobody finds out until a
season is being argued about.

Each check is separate and each one says what it found rather than raising.
A book with problems is still a book, and the office wants the list.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from enum import Enum

from ..errors import ValidationError
from ..ids import DeviceTag, TurnoutCode
from ..model.account import AccountStatus
from .db import query
from .repo_accounts import load_register
from .repo_devices import load_devices
from .repo_ditch import load_system
from .repo_rights import load_ladder
from .serial import int_value, text_value


class Severity(Enum):
    """How much somebody should care."""

    PROBLEM = "problem"
    WARNING = "warning"

    @property
    def stops_the_season(self) -> bool:
        return self is Severity.PROBLEM


@dataclass(frozen=True, slots=True)
class Finding:
    """One thing wrong with the book."""

    check: str
    severity: Severity
    subject: str
    detail: str

    def describe(self) -> str:
        return f"{self.severity.value}: {self.subject}: {self.detail}"


def turnouts_with_no_device(connection: sqlite3.Connection, on: date) -> tuple[Finding, ...]:
    """A turnout nobody is measuring is a turnout nobody can bill."""

    system = load_system(connection)
    measured = {
        device.turnout
        for device in load_devices(connection)
        if device.turnout is not None and device.in_service_on(on)
    }
    return tuple(
        Finding(
            check="turnout_without_device",
            severity=Severity.PROBLEM,
            subject=str(turnout.code),
            detail="nothing is measuring this turnout",
        )
        for turnout in system.all_turnouts()
        if turnout.code not in measured
    )


def devices_out_of_calibration(connection: sqlite3.Connection, on: date) -> tuple[Finding, ...]:
    return tuple(
        Finding(
            check="lapsed_calibration",
            severity=Severity.WARNING,
            subject=str(device.tag),
            detail=f"no calibration stands on {on}",
        )
        for device in load_devices(connection)
        if device.in_service_on(on) and not device.is_calibrated_on(on)
    )


def readings_against_pulled_devices(connection: sqlite3.Connection) -> tuple[Finding, ...]:
    """Readings written after the device came out of the ditch."""

    found: list[Finding] = []
    for device in load_devices(connection):
        if device.removed is None:
            continue
        rows = query(
            connection,
            "SELECT count(*) AS late FROM reading WHERE device_tag = ? AND taken_at >= ?",
            (str(device.tag), device.removed.isoformat()),
        )
        late = int_value(rows[0]["late"], "reading count") if rows else 0
        if late:
            found.append(
                Finding(
                    check="reading_after_removal",
                    severity=Severity.PROBLEM,
                    subject=str(device.tag),
                    detail=f"{late} readings after it was pulled on {device.removed}",
                )
            )
    return tuple(found)


def certificates_at_missing_turnouts(connection: sqlite3.Connection) -> tuple[Finding, ...]:
    system = load_system(connection)
    real = {turnout.code for turnout in system.all_turnouts()}
    register = load_register(connection)
    return tuple(
        Finding(
            check="certificate_off_the_system",
            severity=Severity.PROBLEM,
            subject=certificate.serial,
            detail=f"delivered at {certificate.turnout}, which is not on the system",
        )
        for certificate in register.certificates
        if certificate.retired is None and certificate.turnout not in real
    )


def shares_at_turnouts_nobody_serves(
    connection: sqlite3.Connection, on: date
) -> tuple[Finding, ...]:
    """Turnouts carrying shares with no live account behind them."""

    register = load_register(connection)
    closed = {
        account.number for account in register.accounts if account.status is AccountStatus.CLOSED
    }
    found: list[Finding] = []
    for certificate in register.held_on(on):
        if certificate.account in closed:
            found.append(
                Finding(
                    check="shares_on_a_closed_account",
                    severity=Severity.WARNING,
                    subject=certificate.serial,
                    detail=f"account {certificate.account} is closed and still holds shares",
                )
            )
    return tuple(found)


def rights_on_missing_ditches(connection: sqlite3.Connection) -> tuple[Finding, ...]:
    system = load_system(connection)
    codes = {ditch.code for ditch in system.ditches}
    return tuple(
        Finding(
            check="right_off_the_system",
            severity=Severity.PROBLEM,
            subject=str(right.decree),
            detail=f"decreed to ditch {right.ditch}, which is not on the system",
        )
        for right in load_ladder(connection)
        if right.ditch is not None and right.ditch not in codes
    )


def devices_on_missing_turnouts(connection: sqlite3.Connection) -> tuple[Finding, ...]:
    system = load_system(connection)
    real = {turnout.code for turnout in system.all_turnouts()}
    return tuple(
        Finding(
            check="device_off_the_system",
            severity=Severity.PROBLEM,
            subject=str(device.tag),
            detail=f"installed at {device.turnout}, which is not on the system",
        )
        for device in load_devices(connection)
        if device.turnout is not None and device.turnout not in real
    )


def orphan_readings(connection: sqlite3.Connection) -> tuple[Finding, ...]:
    """Readings against a device tag the book has never heard of."""

    rows = query(
        connection,
        "SELECT DISTINCT device_tag FROM reading WHERE device_tag NOT IN"
        " (SELECT tag FROM device) ORDER BY device_tag",
    )
    return tuple(
        Finding(
            check="orphan_reading",
            severity=Severity.PROBLEM,
            subject=text_value(row["device_tag"], "reading.device_tag"),
            detail="readings against a device that is not in the book",
        )
        for row in rows
    )


def audit(connection: sqlite3.Connection, on: date) -> tuple[Finding, ...]:
    """Every check, in the order the office would want to read them."""

    found: list[Finding] = []
    found.extend(devices_on_missing_turnouts(connection))
    found.extend(turnouts_with_no_device(connection, on))
    found.extend(orphan_readings(connection))
    found.extend(readings_against_pulled_devices(connection))
    found.extend(certificates_at_missing_turnouts(connection))
    found.extend(rights_on_missing_ditches(connection))
    found.extend(devices_out_of_calibration(connection, on))
    found.extend(shares_at_turnouts_nobody_serves(connection, on))
    return tuple(found)


def problems(findings: tuple[Finding, ...]) -> tuple[Finding, ...]:
    return tuple(item for item in findings if item.severity.stops_the_season)


def summarise(findings: tuple[Finding, ...]) -> str:
    if not findings:
        return "nothing wrong with the book"
    counted = len(problems(findings))
    return f"{counted} problems and {len(findings) - counted} warnings"


def known_checks() -> tuple[str, ...]:
    """Every check by name, for anybody wanting to know what was looked at."""

    return (
        "device_off_the_system",
        "turnout_without_device",
        "orphan_reading",
        "reading_after_removal",
        "certificate_off_the_system",
        "right_off_the_system",
        "lapsed_calibration",
        "shares_on_a_closed_account",
    )


def unchecked_volume(connection: sqlite3.Connection) -> Decimal:
    """Deliveries recorded against turnouts that are no longer on the system.

    A number here means somebody has been billed for water at a gate that does
    not exist, which is the sort of thing that turns up when a lateral is
    abandoned and the book is not tidied after it.
    """

    system = load_system(connection)
    real = {str(turnout.code) for turnout in system.all_turnouts()}
    rows = query(
        connection,
        "SELECT turnout_code, sum(CAST(allowed_cfs AS REAL)) AS taken FROM water_order"
        " WHERE status IN ('accepted', 'reduced') GROUP BY turnout_code",
    )
    total = Decimal("0")
    for row in rows:
        code = text_value(row["turnout_code"], "water_order.turnout_code")
        if code not in real and row["taken"] is not None:
            total += Decimal(str(row["taken"]))
    return total


def turnout_codes_in_findings(findings: tuple[Finding, ...]) -> tuple[TurnoutCode, ...]:
    """The turnouts named in a set of findings, for a report that groups them.

    Most subjects are not turnout codes, so the ones that will not parse are
    dropped rather than complained about.
    """

    codes: list[TurnoutCode] = []
    for finding in findings:
        try:
            codes.append(TurnoutCode(finding.subject))
        except ValidationError:
            continue
    return tuple(codes)


def device_tags_in_findings(findings: tuple[Finding, ...]) -> tuple[DeviceTag, ...]:
    """The devices named in a set of findings, dropping what is not a tag."""

    tags: list[DeviceTag] = []
    for finding in findings:
        try:
            tags.append(DeviceTag(finding.subject))
        except ValidationError:
            continue
    return tuple(tags)
