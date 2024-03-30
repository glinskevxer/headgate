"""Reading and writing the canal system.

The system is written as a whole rather than a ditch at a time. A lateral that
refers to a parent that is not there yet is not a state the book should ever be
in, and writing the pieces separately is how it gets into one. Loading rebuilds
the DitchSystem, which validates the whole shape again on the way out, so a
book edited by hand is caught at the point it is read rather than three reports
later.
"""

from __future__ import annotations

import sqlite3

from ..ids import DitchCode, TurnoutCode
from ..model.ditch import Ditch, DitchSystem, Turnout
from ..model.stream import Reach, Stream
from .db import query, transaction
from .serial import (
    decimal_text,
    optional_decimal,
    text_decimal,
    text_value,
)

DITCH_COLUMNS = (
    "code, name, capacity_cfs, length_feet, loss_per_mile, parent_code,"
    " offtake_station_feet, diversion_mile"
)
TURNOUT_COLUMNS = "code, ditch_code, name, station_feet, capacity_cfs, served_acres"
REACH_COLUMNS = "code, name, head_mile, toe_mile, mean_velocity_fps, loss_per_mile"


def save_system(connection: sqlite3.Connection, system: DitchSystem) -> None:
    """Replace the canal system with this one, in a single write."""

    with transaction(connection):
        connection.execute("DELETE FROM turnout")
        connection.execute("DELETE FROM ditch")
        for ditch in _parents_first(system):
            connection.execute(
                f"INSERT INTO ditch ({DITCH_COLUMNS}) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    str(ditch.code),
                    ditch.name,
                    decimal_text(ditch.capacity_cfs),
                    decimal_text(ditch.length_feet),
                    decimal_text(ditch.loss_fraction_per_mile),
                    str(ditch.parent) if ditch.parent is not None else None,
                    decimal_text(ditch.offtake_station_feet)
                    if ditch.offtake_station_feet is not None
                    else None,
                    decimal_text(ditch.diversion_mile)
                    if ditch.diversion_mile is not None
                    else None,
                ),
            )
            for turnout in ditch.turnouts:
                connection.execute(
                    f"INSERT INTO turnout ({TURNOUT_COLUMNS}) VALUES (?, ?, ?, ?, ?, ?)",
                    (
                        str(turnout.code),
                        str(ditch.code),
                        turnout.name,
                        decimal_text(turnout.station_feet),
                        decimal_text(turnout.capacity_cfs),
                        decimal_text(turnout.served_acres),
                    ),
                )


def _parents_first(system: DitchSystem) -> list[Ditch]:
    return _ordered(list(system.ditches))


def _ordered(ditches: list[Ditch]) -> list[Ditch]:
    """Parents before the laterals that leave them, stable by code otherwise."""

    ordered: list[Ditch] = []
    remaining = list(ditches)
    placed: set[DitchCode] = set()
    while remaining:
        for ditch in list(remaining):
            if ditch.parent is None or ditch.parent in placed:
                ordered.append(ditch)
                placed.add(ditch.code)
                remaining.remove(ditch)
    return ordered


def load_system(connection: sqlite3.Connection) -> DitchSystem:
    """Rebuild the canal system, validating it as it comes back."""

    turnouts: dict[str, list[Turnout]] = {}
    for row in query(connection, f"SELECT {TURNOUT_COLUMNS} FROM turnout ORDER BY code"):
        ditch_code = text_value(row["ditch_code"], "turnout.ditch_code")
        turnouts.setdefault(ditch_code, []).append(
            Turnout(
                code=TurnoutCode(text_value(row["code"], "turnout.code")),
                name=text_value(row["name"], "turnout.name"),
                station_feet=text_decimal(row["station_feet"], "turnout.station_feet"),
                capacity_cfs=text_decimal(row["capacity_cfs"], "turnout.capacity_cfs"),
                served_acres=text_decimal(row["served_acres"], "turnout.served_acres"),
            )
        )
    ditches: list[Ditch] = []
    for row in query(connection, f"SELECT {DITCH_COLUMNS} FROM ditch ORDER BY code"):
        code = text_value(row["code"], "ditch.code")
        parent = row["parent_code"]
        ditches.append(
            Ditch(
                code=DitchCode(code),
                name=text_value(row["name"], "ditch.name"),
                capacity_cfs=text_decimal(row["capacity_cfs"], "ditch.capacity_cfs"),
                length_feet=text_decimal(row["length_feet"], "ditch.length_feet"),
                loss_fraction_per_mile=text_decimal(row["loss_per_mile"], "ditch.loss_per_mile"),
                turnouts=tuple(turnouts.get(code, ())),
                parent=DitchCode(text_value(parent, "ditch.parent_code"))
                if parent is not None
                else None,
                offtake_station_feet=optional_decimal(
                    row["offtake_station_feet"], "ditch.offtake_station_feet"
                ),
                diversion_mile=optional_decimal(row["diversion_mile"], "ditch.diversion_mile"),
            )
        )
    return DitchSystem(ditches=tuple(_ordered(ditches)))


def save_stream(connection: sqlite3.Connection, stream: Stream) -> None:
    """Replace the stream description with this one."""

    with transaction(connection):
        connection.execute("DELETE FROM reach")
        for reach in stream.reaches:
            connection.execute(
                f"INSERT INTO reach ({REACH_COLUMNS}) VALUES (?, ?, ?, ?, ?, ?)",
                (
                    reach.code,
                    reach.name,
                    decimal_text(reach.head_mile),
                    decimal_text(reach.toe_mile),
                    decimal_text(reach.mean_velocity_fps),
                    decimal_text(reach.loss_fraction_per_mile),
                ),
            )
        connection.execute(
            "UPDATE district SET stream_name = ? WHERE id = 1",
            (stream.name,),
        )


def load_stream(connection: sqlite3.Connection, name: str) -> Stream:
    """Rebuild the stream, head to toe."""

    reaches = tuple(
        Reach(
            code=text_value(row["code"], "reach.code"),
            name=text_value(row["name"], "reach.name"),
            head_mile=text_decimal(row["head_mile"], "reach.head_mile"),
            toe_mile=text_decimal(row["toe_mile"], "reach.toe_mile"),
            mean_velocity_fps=text_decimal(row["mean_velocity_fps"], "reach.mean_velocity_fps"),
            loss_fraction_per_mile=text_decimal(row["loss_per_mile"], "reach.loss_per_mile"),
        )
        for row in query(connection, f"SELECT {REACH_COLUMNS} FROM reach ORDER BY head_mile DESC")
    )
    return Stream(name=name, reaches=reaches)


def turnout_codes(connection: sqlite3.Connection) -> tuple[TurnoutCode, ...]:
    rows = query(connection, "SELECT code FROM turnout ORDER BY code")
    return tuple(TurnoutCode(text_value(row["code"], "turnout.code")) for row in rows)
