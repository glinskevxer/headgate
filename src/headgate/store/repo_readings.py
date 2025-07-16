"""Reading and writing what the riders wrote down.

Readings are the one table that grows every day, so they are written one at a
time and read back as a series for a single device. The primary key is the
device and the instant together, which is the rule that a device cannot be in
two states at one moment, enforced by the book rather than remembered by the
caller.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Sequence
from datetime import date, datetime

from ..errors import ConflictError
from ..ids import DeviceTag
from ..model.reading import ReadingMethod, ReadingSeries, StaffReading
from ..wateryear import Span
from .db import query, scalar, transaction
from .serial import (
    enum_text,
    instant_text,
    optional_decimal,
    optional_decimal_text,
    text_instant,
    text_value,
)

READING_COLUMNS = (
    "device_tag, taken_at, observer, method, head_feet, tail_feet, meter_total_af, note"
)


def _reading_from(row: sqlite3.Row) -> StaffReading:
    return StaffReading(
        device=DeviceTag(text_value(row["device_tag"], "reading.device_tag")),
        taken_at=text_instant(row["taken_at"], "reading.taken_at"),
        observer=text_value(row["observer"], "reading.observer"),
        method=ReadingMethod(text_value(row["method"], "reading.method")),
        head_feet=optional_decimal(row["head_feet"], "reading.head_feet"),
        tail_feet=optional_decimal(row["tail_feet"], "reading.tail_feet"),
        meter_total_af=optional_decimal(row["meter_total_af"], "reading.meter_total_af"),
        note=text_value(row["note"], "reading.note"),
    )


def save_reading(connection: sqlite3.Connection, reading: StaffReading) -> None:
    """Write one trip to one device. The same instant twice is a conflict."""

    try:
        with transaction(connection):
            connection.execute(
                f"INSERT INTO reading ({READING_COLUMNS}) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    str(reading.device),
                    instant_text(reading.taken_at),
                    reading.observer,
                    enum_text(reading.method),
                    optional_decimal_text(reading.head_feet),
                    optional_decimal_text(reading.tail_feet),
                    optional_decimal_text(reading.meter_total_af),
                    reading.note,
                ),
            )
    except sqlite3.IntegrityError as exc:
        if "reading" in str(exc) and "UNIQUE" in str(exc).upper():
            raise ConflictError(
                f"device {reading.device} was already read at {reading.taken_at}"
            ) from exc
        raise


def save_readings(connection: sqlite3.Connection, readings: Sequence[StaffReading]) -> int:
    """Write a whole file of readings as one transaction.

    A rider's tablet brings back five thousand rows and writing them one at a
    time is five thousand transactions, each with its own fsync, which takes
    minutes on the office machine. This writes them in one, and one bad row
    takes the whole file down rather than leaving half of it in, which is what
    the import command promises.
    """

    if not readings:
        return 0
    rows = [
        (
            str(reading.device),
            instant_text(reading.taken_at),
            reading.observer,
            enum_text(reading.method),
            optional_decimal_text(reading.head_feet),
            optional_decimal_text(reading.tail_feet),
            optional_decimal_text(reading.meter_total_af),
            reading.note,
        )
        for reading in readings
    ]
    try:
        with transaction(connection):
            connection.executemany(
                f"INSERT INTO reading ({READING_COLUMNS}) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                rows,
            )
    except sqlite3.IntegrityError as exc:
        if "UNIQUE" in str(exc).upper():
            raise ConflictError(
                "one of these readings is already in the book, so none of them were written"
            ) from exc
        raise
    return len(rows)


def load_series(connection: sqlite3.Connection, device: DeviceTag) -> ReadingSeries:
    """Every reading on one device, oldest first."""

    rows = query(
        connection,
        f"SELECT {READING_COLUMNS} FROM reading WHERE device_tag = ? ORDER BY taken_at",
        (str(device),),
    )
    return ReadingSeries(device=device, readings=tuple(_reading_from(row) for row in rows))


def load_series_within(
    connection: sqlite3.Connection, device: DeviceTag, span: Span
) -> ReadingSeries:
    """The readings a span needs, including the one that opened it."""

    rows = query(
        connection,
        f"SELECT {READING_COLUMNS} FROM reading WHERE device_tag = ? AND taken_at < ?"
        " ORDER BY taken_at",
        (str(device), instant_text(span.end)),
    )
    readings = [_reading_from(row) for row in rows]
    inside = [item for item in readings if item.taken_at >= span.start]
    before = [item for item in readings if item.taken_at < span.start]
    if before:
        inside.insert(0, before[-1])
    return ReadingSeries(device=device, readings=tuple(inside))


def readings_on(connection: sqlite3.Connection, day: date) -> tuple[StaffReading, ...]:
    """Everything read on one day, across every device."""

    rows = query(
        connection,
        f"SELECT {READING_COLUMNS} FROM reading WHERE taken_at >= ? AND taken_at < ?"
        " ORDER BY taken_at, device_tag",
        (
            instant_text(datetime.combine(day, datetime.min.time())),
            instant_text(datetime.combine(day, datetime.max.time())),
        ),
    )
    return tuple(_reading_from(row) for row in rows)


def devices_read_within(connection: sqlite3.Connection, span: Span) -> tuple[DeviceTag, ...]:
    rows = query(
        connection,
        "SELECT DISTINCT device_tag FROM reading WHERE taken_at >= ? AND taken_at < ?"
        " ORDER BY device_tag",
        (instant_text(span.start), instant_text(span.end)),
    )
    return tuple(DeviceTag(text_value(row["device_tag"], "reading.device_tag")) for row in rows)


def count_readings(connection: sqlite3.Connection, device: DeviceTag | None = None) -> int:
    if device is None:
        return int(scalar(connection, "SELECT count(*) FROM reading") or 0)
    return int(
        scalar(connection, "SELECT count(*) FROM reading WHERE device_tag = ?", (str(device),)) or 0
    )


def delete_reading(connection: sqlite3.Connection, device: DeviceTag, taken_at: datetime) -> bool:
    """Strike a reading that was written against the wrong device."""

    with transaction(connection):
        cursor = connection.execute(
            "DELETE FROM reading WHERE device_tag = ? AND taken_at = ?",
            (str(device), instant_text(taken_at)),
        )
        removed = cursor.rowcount
        cursor.close()
    return removed > 0
