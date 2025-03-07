"""Reading and writing the gaging record.

One row a day a gage, which is the largest table in the book by a long way
after the readings. A day is written once; a corrected day is written over,
because the published gage record is not the district's document and correcting
it is somebody else's decision that this book only follows.
"""

from __future__ import annotations

import sqlite3
from datetime import date
from decimal import Decimal

from ..errors import NotFoundError
from ..model.gage import DailyMean, Hydrograph, RecordGrade
from ..model.stream import GagePoint
from .db import one, query, scalar, transaction
from .serial import (
    date_text,
    decimal_text,
    enum_text,
    text_date,
    text_decimal,
    text_enum,
    text_value,
)

GAGE_COLUMNS = "code, name, river_mile, datum_feet"
DAY_COLUMNS = "gage_code, day, mean_cfs, grade"


def save_gage(connection: sqlite3.Connection, gage: GagePoint) -> None:
    with transaction(connection):
        connection.execute(
            f"INSERT INTO gage ({GAGE_COLUMNS}) VALUES (?, ?, ?, ?)"
            " ON CONFLICT (code) DO UPDATE SET name = excluded.name,"
            " river_mile = excluded.river_mile, datum_feet = excluded.datum_feet",
            (
                gage.code,
                gage.name,
                decimal_text(gage.mile),
                decimal_text(gage.datum_elevation_feet),
            ),
        )


def load_gage(connection: sqlite3.Connection, code: str) -> GagePoint:
    row = one(connection, f"SELECT {GAGE_COLUMNS} FROM gage WHERE code = ?", (code,))
    if row is None:
        raise NotFoundError("gage", code)
    return GagePoint(
        code=text_value(row["code"], "gage.code"),
        name=text_value(row["name"], "gage.name"),
        mile=text_decimal(row["river_mile"], "gage.river_mile"),
        datum_elevation_feet=text_decimal(row["datum_feet"], "gage.datum_feet"),
    )


def gages(connection: sqlite3.Connection) -> tuple[GagePoint, ...]:
    rows = query(connection, f"SELECT {GAGE_COLUMNS} FROM gage ORDER BY river_mile DESC")
    return tuple(
        GagePoint(
            code=text_value(row["code"], "gage.code"),
            name=text_value(row["name"], "gage.name"),
            mile=text_decimal(row["river_mile"], "gage.river_mile"),
            datum_elevation_feet=text_decimal(row["datum_feet"], "gage.datum_feet"),
        )
        for row in rows
    )


def record_day(connection: sqlite3.Connection, code: str, reading: DailyMean) -> None:
    """Write one day, replacing whatever was published for it before."""

    with transaction(connection):
        connection.execute(
            f"INSERT INTO gage_day ({DAY_COLUMNS}) VALUES (?, ?, ?, ?)"
            " ON CONFLICT (gage_code, day) DO UPDATE SET"
            " mean_cfs = excluded.mean_cfs, grade = excluded.grade",
            (
                code,
                date_text(reading.day),
                decimal_text(reading.mean_cfs),
                enum_text(reading.grade),
            ),
        )


def load_hydrograph(
    connection: sqlite3.Connection,
    code: str,
    first: date | None = None,
    last: date | None = None,
) -> Hydrograph:
    """The gage's record, or the part of it inside a span."""

    if first is None or last is None:
        rows = query(
            connection,
            f"SELECT {DAY_COLUMNS} FROM gage_day WHERE gage_code = ? ORDER BY day",
            (code,),
        )
    else:
        rows = query(
            connection,
            f"SELECT {DAY_COLUMNS} FROM gage_day WHERE gage_code = ? AND day >= ? AND day < ?"
            " ORDER BY day",
            (code, date_text(first), date_text(last)),
        )
    return Hydrograph(
        gage=code,
        days=tuple(
            DailyMean(
                day=text_date(row["day"], "gage_day.day"),
                mean_cfs=text_decimal(row["mean_cfs"], "gage_day.mean_cfs"),
                grade=text_enum(RecordGrade, row["grade"], "gage_day.grade"),
            )
            for row in rows
        ),
    )


def count_days(connection: sqlite3.Connection, code: str) -> int:
    return int(
        scalar(connection, "SELECT count(*) FROM gage_day WHERE gage_code = ?", (code,)) or 0
    )


def flow_on(connection: sqlite3.Connection, code: str, day: date) -> Decimal:
    """What the creek was doing at a gage on a day."""

    row = one(
        connection,
        "SELECT mean_cfs FROM gage_day WHERE gage_code = ? AND day = ?",
        (code, date_text(day)),
    )
    if row is None:
        raise NotFoundError("gage record", f"{code} on {day}")
    return text_decimal(row["mean_cfs"], "gage_day.mean_cfs")
