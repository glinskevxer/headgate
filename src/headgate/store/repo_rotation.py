"""Reading and writing the rotation.

The windows are written for a water year and replaced wholesale when the
commissioner rebuilds the cycle, because a rotation is a plan and half of an
old plan mixed into a new one is not a plan at all.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime
from decimal import Decimal

from ..errors import PolicyError
from ..ids import TurnoutCode
from ..rotation.plan import RotationPlan, RunWindow
from ..wateryear import Span
from .db import query, scalar, transaction
from .serial import decimal_text, instant_text, int_value, text_decimal, text_instant, text_value

WINDOW_COLUMNS = "water_year, turnout_code, run_from, run_to, rate_cfs"


def _window_from(row: sqlite3.Row) -> RunWindow:
    return RunWindow(
        turnout=TurnoutCode(text_value(row["turnout_code"], "rotation_window.turnout_code")),
        span=Span(
            text_instant(row["run_from"], "rotation_window.run_from"),
            text_instant(row["run_to"], "rotation_window.run_to"),
        ),
        rate_cfs=text_decimal(row["rate_cfs"], "rotation_window.rate_cfs"),
    )


def save_plan(connection: sqlite3.Connection, plan: RotationPlan) -> None:
    """Replace the year's rotation with this one, in a single write."""

    with transaction(connection):
        connection.execute("DELETE FROM rotation_window WHERE water_year = ?", (plan.water_year,))
        for window in plan.windows:
            connection.execute(
                f"INSERT INTO rotation_window ({WINDOW_COLUMNS}) VALUES (?, ?, ?, ?, ?)",
                (
                    plan.water_year,
                    str(window.turnout),
                    instant_text(window.span.start),
                    instant_text(window.span.end),
                    decimal_text(window.rate_cfs),
                ),
            )


def load_plan(connection: sqlite3.Connection, water_year: int) -> RotationPlan:
    rows = query(
        connection,
        f"SELECT {WINDOW_COLUMNS} FROM rotation_window WHERE water_year = ?"
        " ORDER BY run_from, turnout_code",
        (water_year,),
    )
    return RotationPlan(water_year=water_year, windows=tuple(_window_from(row) for row in rows))


def running_at(connection: sqlite3.Connection, moment: datetime) -> tuple[RunWindow, ...]:
    """The windows open at a moment, whatever year they belong to."""

    rows = query(
        connection,
        f"SELECT {WINDOW_COLUMNS} FROM rotation_window WHERE run_from <= ? AND run_to > ?"
        " ORDER BY turnout_code",
        (instant_text(moment), instant_text(moment)),
    )
    return tuple(_window_from(row) for row in rows)


def next_window(connection: sqlite3.Connection, turnout: TurnoutCode, after: datetime) -> RunWindow:
    """When a turnout comes round again, which is the question riders ask."""

    rows = query(
        connection,
        f"SELECT {WINDOW_COLUMNS} FROM rotation_window WHERE turnout_code = ?"
        " AND run_from > ? ORDER BY run_from LIMIT 1",
        (str(turnout), instant_text(after)),
    )
    if not rows:
        raise PolicyError(f"turnout {turnout} does not come round again after {after}")
    return _window_from(rows[0])


def hours_for(connection: sqlite3.Connection, turnout: TurnoutCode, water_year: int) -> Decimal:
    return load_plan(connection, water_year).hours_for(turnout)


def count_windows(connection: sqlite3.Connection, water_year: int) -> int:
    return int(
        scalar(
            connection,
            "SELECT count(*) FROM rotation_window WHERE water_year = ?",
            (water_year,),
        )
        or 0
    )


def years_planned(connection: sqlite3.Connection) -> tuple[int, ...]:
    rows = query(
        connection,
        "SELECT DISTINCT water_year FROM rotation_window ORDER BY water_year",
    )
    return tuple(int_value(row["water_year"], "rotation_window.water_year") for row in rows)
