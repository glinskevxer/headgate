"""The declared season, one row a water year.

The board declares the season each spring and sometimes moves the closing date
in August when the creek does not hold up. Both dates are stored, along with
the day the board voted, because a delivery outside the season is treated
differently and somebody will want to know what the rule was at the time.
"""

from __future__ import annotations

import sqlite3
from datetime import date

from ..errors import ConflictError, NotFoundError, PolicyError
from ..wateryear import IrrigationSeason, water_year_of
from .db import one, query, transaction
from .serial import date_text, int_value, text_date, text_value

SEASON_COLUMNS = "water_year, opened, closed, declared_on, note"


def _season_from(row: sqlite3.Row) -> IrrigationSeason:
    return IrrigationSeason(
        water_year=int_value(row["water_year"], "season.water_year"),
        opened=text_date(row["opened"], "season.opened"),
        closed=text_date(row["closed"], "season.closed"),
    )


def declare_season(
    connection: sqlite3.Connection,
    season: IrrigationSeason,
    declared_on: date,
    note: str = "",
) -> IrrigationSeason:
    """Record the board's declaration for a water year."""

    if declared_on > season.opened:
        raise PolicyError(
            f"the season for {season.water_year} opens {season.opened} and was declared "
            f"{declared_on}, which is after the water was already running"
        )
    existing = one(
        connection,
        "SELECT water_year FROM season WHERE water_year = ?",
        (season.water_year,),
    )
    if existing is not None:
        raise ConflictError(f"the season for {season.water_year} has already been declared")
    with transaction(connection):
        connection.execute(
            f"INSERT INTO season ({SEASON_COLUMNS}) VALUES (?, ?, ?, ?, ?)",
            (
                season.water_year,
                date_text(season.opened),
                date_text(season.closed),
                date_text(declared_on),
                note,
            ),
        )
    return season


def load_season(connection: sqlite3.Connection, water_year: int) -> IrrigationSeason:
    row = one(
        connection, f"SELECT {SEASON_COLUMNS} FROM season WHERE water_year = ?", (water_year,)
    )
    if row is None:
        raise NotFoundError("season", str(water_year))
    return _season_from(row)


def season_for(connection: sqlite3.Connection, day: date) -> IrrigationSeason:
    """The season a day falls in, which is not always the one it looks like."""

    season = load_season(connection, water_year_of(day))
    if not season.covers(day):
        raise PolicyError(f"{day} is outside the declared season for {season.water_year}")
    return season


def list_seasons(connection: sqlite3.Connection) -> tuple[IrrigationSeason, ...]:
    rows = query(connection, f"SELECT {SEASON_COLUMNS} FROM season ORDER BY water_year")
    return tuple(_season_from(row) for row in rows)


def close_early(
    connection: sqlite3.Connection, water_year: int, closed: date, note: str
) -> IrrigationSeason:
    """Move the closing date in, which is what a short year looks like."""

    season = load_season(connection, water_year)
    if closed >= season.closed:
        raise PolicyError(
            f"closing {water_year} on {closed} is not earlier than the declared {season.closed}"
        )
    shortened = IrrigationSeason(water_year=water_year, opened=season.opened, closed=closed)
    with transaction(connection):
        connection.execute(
            "UPDATE season SET closed = ?, note = ? WHERE water_year = ?",
            (date_text(closed), note, water_year),
        )
    return shortened


def declaration_note(connection: sqlite3.Connection, water_year: int) -> str:
    row = one(connection, "SELECT note FROM season WHERE water_year = ?", (water_year,))
    if row is None:
        raise NotFoundError("season", str(water_year))
    return text_value(row["note"], "season.note")
