"""Reading and writing the decrees.

A right is stored flat, with its priority spread across three columns, because
that is what an index can sort. The ladder is rebuilt in priority order on the
way out so no caller has to remember that appropriation date alone does not
break a tie.
"""

from __future__ import annotations

import sqlite3
from datetime import date

from ..errors import NotFoundError
from ..ids import DecreeNumber, DitchCode
from ..model.right import Priority, RightKind, RightStatus, WaterRight, order_by_priority
from .db import one, query, transaction
from .serial import (
    code_text,
    date_text,
    decimal_text,
    enum_text,
    int_value,
    optional_decimal,
    optional_decimal_text,
    text_date,
    text_decimal,
    text_enum,
    text_value,
)

RIGHT_COLUMNS = (
    "decree, owner, kind, appropriation_date, adjudication_year, sequence_number,"
    " diversion_mile, rate_cfs, volume_af, ditch_code, status"
)


def _right_from(row: sqlite3.Row) -> WaterRight:
    ditch = row["ditch_code"]
    return WaterRight(
        decree=DecreeNumber(text_value(row["decree"], "water_right.decree")),
        owner=text_value(row["owner"], "water_right.owner"),
        kind=text_enum(RightKind, row["kind"], "water_right.kind"),
        priority=Priority(
            appropriation_date=text_date(
                row["appropriation_date"], "water_right.appropriation_date"
            ),
            adjudication_year=int_value(row["adjudication_year"], "water_right.adjudication_year"),
            sequence=int_value(row["sequence_number"], "water_right.sequence_number"),
        ),
        diversion_mile=text_decimal(row["diversion_mile"], "water_right.diversion_mile"),
        rate_cfs=optional_decimal(row["rate_cfs"], "water_right.rate_cfs"),
        volume_af=optional_decimal(row["volume_af"], "water_right.volume_af"),
        ditch=DitchCode(text_value(ditch, "water_right.ditch_code")) if ditch is not None else None,
        status=text_enum(RightStatus, row["status"], "water_right.status"),
    )


def save_right(connection: sqlite3.Connection, right: WaterRight) -> None:
    """Write a decree, replacing what stood under that number."""

    with transaction(connection):
        connection.execute(
            f"INSERT INTO water_right ({RIGHT_COLUMNS})"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"
            " ON CONFLICT (decree) DO UPDATE SET"
            " owner = excluded.owner, kind = excluded.kind,"
            " appropriation_date = excluded.appropriation_date,"
            " adjudication_year = excluded.adjudication_year,"
            " sequence_number = excluded.sequence_number,"
            " diversion_mile = excluded.diversion_mile, rate_cfs = excluded.rate_cfs,"
            " volume_af = excluded.volume_af, ditch_code = excluded.ditch_code,"
            " status = excluded.status",
            (
                str(right.decree),
                right.owner,
                enum_text(right.kind),
                date_text(right.priority.appropriation_date),
                right.priority.adjudication_year,
                right.priority.sequence,
                decimal_text(right.diversion_mile),
                optional_decimal_text(right.rate_cfs),
                optional_decimal_text(right.volume_af),
                code_text(right.ditch),
                enum_text(right.status),
            ),
        )


def load_right(connection: sqlite3.Connection, decree: DecreeNumber) -> WaterRight:
    row = one(
        connection, f"SELECT {RIGHT_COLUMNS} FROM water_right WHERE decree = ?", (str(decree),)
    )
    if row is None:
        raise NotFoundError("decree", str(decree))
    return _right_from(row)


def load_ladder(connection: sqlite3.Connection) -> list[WaterRight]:
    """Every decree on the stream, most senior first."""

    rows = query(connection, f"SELECT {RIGHT_COLUMNS} FROM water_right")
    return order_by_priority([_right_from(row) for row in rows])


def load_active_ladder(connection: sqlite3.Connection) -> list[WaterRight]:
    """The decrees that are still administered, most senior first."""

    return [right for right in load_ladder(connection) if right.is_active]


def rights_on_ditch(connection: sqlite3.Connection, ditch: DitchCode) -> list[WaterRight]:
    rows = query(
        connection,
        f"SELECT {RIGHT_COLUMNS} FROM water_right WHERE ditch_code = ?",
        (str(ditch),),
    )
    return order_by_priority([_right_from(row) for row in rows])


def rights_senior_to(connection: sqlite3.Connection, appropriated: date) -> list[WaterRight]:
    rows = query(
        connection,
        f"SELECT {RIGHT_COLUMNS} FROM water_right WHERE appropriation_date < ?",
        (date_text(appropriated),),
    )
    return order_by_priority([_right_from(row) for row in rows])


def set_status(
    connection: sqlite3.Connection, decree: DecreeNumber, status: RightStatus
) -> WaterRight:
    """Change a decree's standing, which the court does and the office records."""

    right = load_right(connection, decree)
    with transaction(connection):
        connection.execute(
            "UPDATE water_right SET status = ? WHERE decree = ?",
            (enum_text(status), str(decree)),
        )
    return load_right(connection, right.decree)
