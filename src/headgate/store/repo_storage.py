"""Reading and writing the reservoir and the storage accounts.

The pool and the accounts are written separately because they change at
different times. Water comes into the pool every day of the fill and the
accounts only move when somebody is allocated water, draws it, or loses it to a
spill. Reading them back together is the caller's job, and it is worth doing in
one transaction when it matters.
"""

from __future__ import annotations

import sqlite3
from decimal import Decimal

from ..errors import NotFoundError
from ..ids import AccountNumber, DecreeNumber
from ..model.reservoir import PoolState, Reservoir
from ..storage.account import StorageBook, StorageEntry
from .db import one, query, transaction
from .serial import decimal_text, flag_int, int_flag, int_value, text_decimal, text_value

RESERVOIR_COLUMNS = (
    "name, decree, capacity_af, dead_pool_af, fill_opens_month, fill_opens_day,"
    " fill_closes_month, fill_closes_day"
)
POOL_COLUMNS = (
    "reservoir_name, water_year, contents_af, filled_af, spilled_af, released_af, fill_finished"
)
ENTRY_COLUMNS = (
    "reservoir_name, water_year, account_number, shares, allocated_af, released_af,"
    " spilled_af, carried_in_af"
)


def save_reservoir(connection: sqlite3.Connection, reservoir: Reservoir) -> None:
    with transaction(connection):
        connection.execute(
            f"INSERT INTO reservoir ({RESERVOIR_COLUMNS}) VALUES (?, ?, ?, ?, ?, ?, ?, ?)"
            " ON CONFLICT (name) DO UPDATE SET"
            " decree = excluded.decree, capacity_af = excluded.capacity_af,"
            " dead_pool_af = excluded.dead_pool_af,"
            " fill_opens_month = excluded.fill_opens_month,"
            " fill_opens_day = excluded.fill_opens_day,"
            " fill_closes_month = excluded.fill_closes_month,"
            " fill_closes_day = excluded.fill_closes_day",
            (
                reservoir.name,
                str(reservoir.decree),
                decimal_text(reservoir.capacity_af),
                decimal_text(reservoir.dead_pool_af),
                reservoir.fill_opens[0],
                reservoir.fill_opens[1],
                reservoir.fill_closes[0],
                reservoir.fill_closes[1],
            ),
        )


def load_reservoir(connection: sqlite3.Connection, name: str) -> Reservoir:
    row = one(connection, f"SELECT {RESERVOIR_COLUMNS} FROM reservoir WHERE name = ?", (name,))
    if row is None:
        raise NotFoundError("reservoir", name)
    return Reservoir(
        name=text_value(row["name"], "reservoir.name"),
        decree=DecreeNumber(text_value(row["decree"], "reservoir.decree")),
        capacity_af=text_decimal(row["capacity_af"], "reservoir.capacity_af"),
        dead_pool_af=text_decimal(row["dead_pool_af"], "reservoir.dead_pool_af"),
        fill_opens=(
            int_value(row["fill_opens_month"], "reservoir.fill_opens_month"),
            int_value(row["fill_opens_day"], "reservoir.fill_opens_day"),
        ),
        fill_closes=(
            int_value(row["fill_closes_month"], "reservoir.fill_closes_month"),
            int_value(row["fill_closes_day"], "reservoir.fill_closes_day"),
        ),
    )


def save_pool(connection: sqlite3.Connection, pool: PoolState) -> None:
    with transaction(connection):
        connection.execute(
            f"INSERT INTO pool_state ({POOL_COLUMNS}) VALUES (?, ?, ?, ?, ?, ?, ?)"
            " ON CONFLICT (reservoir_name, water_year) DO UPDATE SET"
            " contents_af = excluded.contents_af, filled_af = excluded.filled_af,"
            " spilled_af = excluded.spilled_af, released_af = excluded.released_af,"
            " fill_finished = excluded.fill_finished",
            (
                pool.reservoir.name,
                pool.water_year,
                decimal_text(pool.contents_af),
                decimal_text(pool.filled_af),
                decimal_text(pool.spilled_af),
                decimal_text(pool.released_af),
                flag_int(pool.fill_finished),
            ),
        )


def load_pool(connection: sqlite3.Connection, name: str, water_year: int) -> PoolState:
    row = one(
        connection,
        f"SELECT {POOL_COLUMNS} FROM pool_state WHERE reservoir_name = ? AND water_year = ?",
        (name, water_year),
    )
    if row is None:
        raise NotFoundError("pool", f"{name} in {water_year}")
    return PoolState(
        reservoir=load_reservoir(connection, name),
        water_year=int_value(row["water_year"], "pool_state.water_year"),
        contents_af=text_decimal(row["contents_af"], "pool_state.contents_af"),
        filled_af=text_decimal(row["filled_af"], "pool_state.filled_af"),
        spilled_af=text_decimal(row["spilled_af"], "pool_state.spilled_af"),
        released_af=text_decimal(row["released_af"], "pool_state.released_af"),
        fill_finished=int_flag(row["fill_finished"], "pool_state.fill_finished"),
    )


def save_storage_book(connection: sqlite3.Connection, name: str, book: StorageBook) -> None:
    """Write every account's storage for one year, replacing what stood."""

    with transaction(connection):
        connection.execute(
            "DELETE FROM storage_entry WHERE reservoir_name = ? AND water_year = ?",
            (name, book.water_year),
        )
        for entry in book.entries:
            connection.execute(
                f"INSERT INTO storage_entry ({ENTRY_COLUMNS}) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    name,
                    book.water_year,
                    entry.account.number,
                    decimal_text(entry.shares),
                    decimal_text(entry.allocated_af),
                    decimal_text(entry.released_af),
                    decimal_text(entry.spilled_af),
                    decimal_text(entry.carried_in_af),
                ),
            )


def load_storage_book(connection: sqlite3.Connection, name: str, water_year: int) -> StorageBook:
    rows = query(
        connection,
        f"SELECT {ENTRY_COLUMNS} FROM storage_entry WHERE reservoir_name = ?"
        " AND water_year = ? ORDER BY account_number",
        (name, water_year),
    )
    if not rows:
        raise NotFoundError("storage book", f"{name} in {water_year}")
    entries = tuple(
        StorageEntry(
            account=AccountNumber(int_value(row["account_number"], "storage_entry.account")),
            shares=text_decimal(row["shares"], "storage_entry.shares"),
            allocated_af=text_decimal(row["allocated_af"], "storage_entry.allocated_af"),
            released_af=text_decimal(row["released_af"], "storage_entry.released_af"),
            spilled_af=text_decimal(row["spilled_af"], "storage_entry.spilled_af"),
            carried_in_af=text_decimal(row["carried_in_af"], "storage_entry.carried_in_af"),
        )
        for row in rows
    )
    return StorageBook(water_year=water_year, entries=entries)


def stored_for(connection: sqlite3.Connection, account: AccountNumber, water_year: int) -> Decimal:
    """What one account has left in storage this year, across reservoirs."""

    rows = query(
        connection,
        f"SELECT {ENTRY_COLUMNS} FROM storage_entry WHERE account_number = ? AND water_year = ?",
        (account.number, water_year),
    )
    total = Decimal("0")
    for row in rows:
        entry = StorageEntry(
            account=account,
            shares=text_decimal(row["shares"], "storage_entry.shares"),
            allocated_af=text_decimal(row["allocated_af"], "storage_entry.allocated_af"),
            released_af=text_decimal(row["released_af"], "storage_entry.released_af"),
            spilled_af=text_decimal(row["spilled_af"], "storage_entry.spilled_af"),
            carried_in_af=text_decimal(row["carried_in_af"], "storage_entry.carried_in_af"),
        )
        total += entry.balance_af
    return total
