"""Reading and writing the structures and their calibration history.

A device and its calibrations are written together. A calibration on its own is
not a fact about anything, and a device whose history arrives separately can be
read in a state where a lapsed calibration looks current, which is exactly the
mistake the provenance rules exist to catch.
"""

from __future__ import annotations

import sqlite3
from datetime import date

from ..errors import NotFoundError
from ..ids import DeviceTag, DitchCode, TurnoutCode
from ..model.device import Calibration, Device, DeviceKind
from .db import one, query, transaction
from .serial import (
    code_text,
    date_text,
    decimal_text,
    enum_text,
    int_value,
    optional_date,
    optional_date_text,
    optional_decimal,
    optional_decimal_text,
    text_date,
    text_decimal,
    text_enum,
    text_value,
)

DEVICE_COLUMNS = (
    "tag, kind, installed, removed, crest_width_feet, throat_width_feet,"
    " opening_height_feet, end_contractions, min_head_feet, max_head_feet,"
    " turnout_code, ditch_code"
)
CALIBRATION_COLUMNS = "device_tag, performed, performed_by, expires, staff_offset_feet, note"


def _calibrations_for(connection: sqlite3.Connection, tag: str) -> tuple[Calibration, ...]:
    rows = query(
        connection,
        f"SELECT {CALIBRATION_COLUMNS} FROM calibration WHERE device_tag = ? ORDER BY performed",
        (tag,),
    )
    return tuple(
        Calibration(
            performed=text_date(row["performed"], "calibration.performed"),
            performed_by=text_value(row["performed_by"], "calibration.performed_by"),
            expires=text_date(row["expires"], "calibration.expires"),
            staff_offset_feet=text_decimal(
                row["staff_offset_feet"], "calibration.staff_offset_feet"
            ),
            note=text_value(row["note"], "calibration.note"),
        )
        for row in rows
    )


def _device_from(connection: sqlite3.Connection, row: sqlite3.Row) -> Device:
    tag = text_value(row["tag"], "device.tag")
    turnout = row["turnout_code"]
    ditch = row["ditch_code"]
    return Device(
        tag=DeviceTag(tag),
        kind=text_enum(DeviceKind, row["kind"], "device.kind"),
        installed=text_date(row["installed"], "device.installed"),
        crest_width_feet=optional_decimal(row["crest_width_feet"], "device.crest_width_feet"),
        throat_width_feet=optional_decimal(row["throat_width_feet"], "device.throat_width_feet"),
        opening_height_feet=optional_decimal(
            row["opening_height_feet"], "device.opening_height_feet"
        ),
        end_contractions=int_value(row["end_contractions"], "device.end_contractions"),
        min_head_feet=text_decimal(row["min_head_feet"], "device.min_head_feet"),
        max_head_feet=text_decimal(row["max_head_feet"], "device.max_head_feet"),
        turnout=TurnoutCode(text_value(turnout, "device.turnout_code"))
        if turnout is not None
        else None,
        ditch=DitchCode(text_value(ditch, "device.ditch_code")) if ditch is not None else None,
        removed=optional_date(row["removed"], "device.removed"),
        calibrations=_calibrations_for(connection, tag),
    )


def save_device(connection: sqlite3.Connection, device: Device) -> None:
    """Write a device and the whole of its calibration history."""

    with transaction(connection):
        connection.execute(
            f"INSERT INTO device ({DEVICE_COLUMNS})"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"
            " ON CONFLICT (tag) DO UPDATE SET"
            " kind = excluded.kind, installed = excluded.installed, removed = excluded.removed,"
            " crest_width_feet = excluded.crest_width_feet,"
            " throat_width_feet = excluded.throat_width_feet,"
            " opening_height_feet = excluded.opening_height_feet,"
            " end_contractions = excluded.end_contractions,"
            " min_head_feet = excluded.min_head_feet, max_head_feet = excluded.max_head_feet,"
            " turnout_code = excluded.turnout_code, ditch_code = excluded.ditch_code",
            (
                str(device.tag),
                enum_text(device.kind),
                date_text(device.installed),
                optional_date_text(device.removed),
                optional_decimal_text(device.crest_width_feet),
                optional_decimal_text(device.throat_width_feet),
                optional_decimal_text(device.opening_height_feet),
                device.end_contractions,
                decimal_text(device.min_head_feet),
                decimal_text(device.max_head_feet),
                code_text(device.turnout),
                code_text(device.ditch),
            ),
        )
        for calibration in device.calibrations:
            connection.execute(
                f"INSERT INTO calibration ({CALIBRATION_COLUMNS}) VALUES (?, ?, ?, ?, ?, ?)"
                " ON CONFLICT (device_tag, performed) DO UPDATE SET"
                " performed_by = excluded.performed_by, expires = excluded.expires,"
                " staff_offset_feet = excluded.staff_offset_feet, note = excluded.note",
                (
                    str(device.tag),
                    date_text(calibration.performed),
                    calibration.performed_by,
                    date_text(calibration.expires),
                    decimal_text(calibration.staff_offset_feet),
                    calibration.note,
                ),
            )


def load_device(connection: sqlite3.Connection, tag: DeviceTag) -> Device:
    row = one(connection, f"SELECT {DEVICE_COLUMNS} FROM device WHERE tag = ?", (str(tag),))
    if row is None:
        raise NotFoundError("device", str(tag))
    return _device_from(connection, row)


def load_devices(connection: sqlite3.Connection) -> tuple[Device, ...]:
    rows = query(connection, f"SELECT {DEVICE_COLUMNS} FROM device ORDER BY tag")
    return tuple(_device_from(connection, row) for row in rows)


def device_at_turnout(connection: sqlite3.Connection, turnout: TurnoutCode, on: date) -> Device:
    """The device that was in that turnout on a day."""

    rows = query(
        connection,
        f"SELECT {DEVICE_COLUMNS} FROM device WHERE turnout_code = ? ORDER BY installed",
        (str(turnout),),
    )
    for row in rows:
        device = _device_from(connection, row)
        if device.in_service_on(on):
            return device
    raise NotFoundError("device in service", f"{turnout} on {on}")


def uncalibrated_on(connection: sqlite3.Connection, day: date) -> tuple[Device, ...]:
    """Every device in the ditch that day with no calibration standing."""

    return tuple(
        device
        for device in load_devices(connection)
        if device.in_service_on(day) and not device.is_calibrated_on(day)
    )
