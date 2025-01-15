"""Reading and writing the rate schedule.

A schedule is adopted once a year and then billed against for a decade of
arguments, so it is written whole and read whole. Changing one after the bills
have gone out is not an update; it is a new schedule and a restatement, and
this module will not let a year be adopted twice.
"""

from __future__ import annotations

import sqlite3
from datetime import date
from decimal import Decimal

from ..assessment.tiers import Band, RateSchedule
from ..errors import ConflictError, NotFoundError
from ..money import Money
from .db import one, query, transaction
from .serial import date_text, int_value, optional_decimal, optional_decimal_text, text_date

SCHEDULE_COLUMNS = "water_year, per_share_cents, minimum_bill_cents, adopted_on, note"
BAND_COLUMNS = "water_year, ordinal, upper_af, rate_cents_per_af"


def adopt(
    connection: sqlite3.Connection,
    schedule: RateSchedule,
    adopted_on: date,
    note: str = "",
) -> None:
    """Write the schedule the board adopted for a year."""

    existing = one(
        connection,
        "SELECT water_year FROM rate_schedule WHERE water_year = ?",
        (schedule.water_year,),
    )
    if existing is not None:
        raise ConflictError(f"the {schedule.water_year} rate schedule has already been adopted")
    with transaction(connection):
        connection.execute(
            f"INSERT INTO rate_schedule ({SCHEDULE_COLUMNS}) VALUES (?, ?, ?, ?, ?)",
            (
                schedule.water_year,
                schedule.per_share.cents,
                schedule.minimum_bill.cents,
                date_text(adopted_on),
                note,
            ),
        )
        for ordinal, band in enumerate(schedule.bands, start=1):
            connection.execute(
                f"INSERT INTO rate_band ({BAND_COLUMNS}) VALUES (?, ?, ?, ?)",
                (
                    schedule.water_year,
                    ordinal,
                    optional_decimal_text(band.upper_af),
                    band.rate_per_af.cents,
                ),
            )


def load_schedule(connection: sqlite3.Connection, water_year: int) -> RateSchedule:
    row = one(
        connection,
        f"SELECT {SCHEDULE_COLUMNS} FROM rate_schedule WHERE water_year = ?",
        (water_year,),
    )
    if row is None:
        raise NotFoundError("rate schedule", str(water_year))
    bands = query(
        connection,
        f"SELECT {BAND_COLUMNS} FROM rate_band WHERE water_year = ? ORDER BY ordinal",
        (water_year,),
    )
    return RateSchedule(
        water_year=water_year,
        per_share=Money(int_value(row["per_share_cents"], "rate_schedule.per_share_cents")),
        bands=tuple(
            Band(
                upper_af=optional_decimal(band["upper_af"], "rate_band.upper_af"),
                rate_per_af=Money(
                    int_value(band["rate_cents_per_af"], "rate_band.rate_cents_per_af")
                ),
            )
            for band in bands
        ),
        minimum_bill=Money(
            int_value(row["minimum_bill_cents"], "rate_schedule.minimum_bill_cents")
        ),
    )


def adopted_on(connection: sqlite3.Connection, water_year: int) -> date:
    row = one(
        connection,
        "SELECT adopted_on FROM rate_schedule WHERE water_year = ?",
        (water_year,),
    )
    if row is None:
        raise NotFoundError("rate schedule", str(water_year))
    return text_date(row["adopted_on"], "rate_schedule.adopted_on")


def adopted_years(connection: sqlite3.Connection) -> tuple[int, ...]:
    rows = query(connection, "SELECT water_year FROM rate_schedule ORDER BY water_year")
    return tuple(int_value(row["water_year"], "rate_schedule.water_year") for row in rows)


def charge_for(
    connection: sqlite3.Connection, water_year: int, shares: Decimal, acre_feet: Decimal
) -> Money:
    """What a shareholder would be billed under the year's schedule."""

    return load_schedule(connection, water_year).bill_for(shares, acre_feet)
