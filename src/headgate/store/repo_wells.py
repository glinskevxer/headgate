"""Reading and writing the wells and what they pumped.

Pumping is recorded by the month because that is how the meters are read and
how the depletion is worked. A month written twice is the same month corrected,
so it overwrites: nobody pumps the same month twice.
"""

from __future__ import annotations

import sqlite3
from decimal import Decimal

from ..errors import NotFoundError
from ..ids import DecreeNumber
from ..units import round_volume
from ..wells.depletion import PumpingRecord, Well
from .db import one, query, scalar, transaction
from .serial import (
    decimal_text,
    int_value,
    optional_decimal,
    optional_decimal_text,
    text_decimal,
    text_value,
)

WELL_COLUMNS = (
    "well_id, decree, distance_feet, storativity, transmissivity, capacity_gpm, annual_limit_af"
)
PUMPING_COLUMNS = "well_id, water_year, month, pumped_af"


def _well_from(row: sqlite3.Row) -> Well:
    return Well(
        well_id=text_value(row["well_id"], "well.well_id"),
        decree=DecreeNumber(text_value(row["decree"], "well.decree")),
        distance_to_stream_feet=text_decimal(row["distance_feet"], "well.distance_feet"),
        storativity=text_decimal(row["storativity"], "well.storativity"),
        transmissivity_ft2_day=text_decimal(row["transmissivity"], "well.transmissivity"),
        capacity_gpm=text_decimal(row["capacity_gpm"], "well.capacity_gpm"),
        annual_limit_af=optional_decimal(row["annual_limit_af"], "well.annual_limit_af"),
    )


def save_well(connection: sqlite3.Connection, well: Well) -> None:
    with transaction(connection):
        connection.execute(
            f"INSERT INTO well ({WELL_COLUMNS}) VALUES (?, ?, ?, ?, ?, ?, ?)"
            " ON CONFLICT (well_id) DO UPDATE SET decree = excluded.decree,"
            " distance_feet = excluded.distance_feet, storativity = excluded.storativity,"
            " transmissivity = excluded.transmissivity,"
            " capacity_gpm = excluded.capacity_gpm,"
            " annual_limit_af = excluded.annual_limit_af",
            (
                well.well_id,
                str(well.decree),
                decimal_text(well.distance_to_stream_feet),
                decimal_text(well.storativity),
                decimal_text(well.transmissivity_ft2_day),
                decimal_text(well.capacity_gpm),
                optional_decimal_text(well.annual_limit_af),
            ),
        )


def load_well(connection: sqlite3.Connection, well_id: str) -> Well:
    row = one(connection, f"SELECT {WELL_COLUMNS} FROM well WHERE well_id = ?", (well_id,))
    if row is None:
        raise NotFoundError("well", well_id)
    return _well_from(row)


def load_wells(connection: sqlite3.Connection) -> tuple[Well, ...]:
    rows = query(connection, f"SELECT {WELL_COLUMNS} FROM well ORDER BY well_id")
    return tuple(_well_from(row) for row in rows)


def record_pumping(
    connection: sqlite3.Connection,
    well_id: str,
    water_year: int,
    month: int,
    pumped_af: Decimal,
) -> None:
    """Write one month's pumping, replacing a month read wrong."""

    load_well(connection, well_id)
    with transaction(connection):
        connection.execute(
            f"INSERT INTO well_pumping ({PUMPING_COLUMNS}) VALUES (?, ?, ?, ?)"
            " ON CONFLICT (well_id, water_year, month) DO UPDATE SET"
            " pumped_af = excluded.pumped_af",
            (well_id, water_year, month, decimal_text(pumped_af)),
        )


def pumping_for(
    connection: sqlite3.Connection, well_id: str, water_year: int
) -> tuple[PumpingRecord, ...]:
    well = load_well(connection, well_id)
    rows = query(
        connection,
        f"SELECT {PUMPING_COLUMNS} FROM well_pumping WHERE well_id = ? AND water_year = ?"
        " ORDER BY month",
        (well_id, water_year),
    )
    return tuple(
        PumpingRecord(
            well=well,
            month=int_value(row["month"], "well_pumping.month"),
            pumped_af=text_decimal(row["pumped_af"], "well_pumping.pumped_af"),
        )
        for row in rows
    )


def pumping_in(connection: sqlite3.Connection, water_year: int) -> tuple[PumpingRecord, ...]:
    """Every well's pumping for a year, which is what a plan is measured against."""

    rows = query(
        connection,
        "SELECT DISTINCT well_id FROM well_pumping WHERE water_year = ? ORDER BY well_id",
        (water_year,),
    )
    found: list[PumpingRecord] = []
    for row in rows:
        found.extend(
            pumping_for(connection, text_value(row["well_id"], "well_pumping.well_id"), water_year)
        )
    return tuple(found)


def pumped_total(connection: sqlite3.Connection, well_id: str, water_year: int) -> Decimal:
    total = scalar(
        connection,
        "SELECT sum(CAST(pumped_af AS REAL)) FROM well_pumping WHERE well_id = ?"
        " AND water_year = ?",
        (well_id, water_year),
    )
    return round_volume(Decimal(str(total))) if total is not None else Decimal("0")
