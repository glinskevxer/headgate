"""Reading and writing the lease book.

A lease is written when it is offered and updated as it is approved and
delivered against, which is the one place in this system where a row genuinely
does change: the delivered volume climbs through the season and the paper the
two shareholders signed is not what changes with it.
"""

from __future__ import annotations

import sqlite3
from decimal import Decimal

from ..errors import ConflictError, NotFoundError
from ..ids import AccountNumber
from ..lease.agreement import Lease, LeaseBook, LeaseSource, LeaseStatus
from ..money import Money
from .db import one, query, transaction
from .serial import (
    date_text,
    decimal_text,
    enum_text,
    int_value,
    text_date,
    text_decimal,
    text_enum,
    text_value,
)

LEASE_COLUMNS = (
    "number, water_year, lessor, lessee, source, volume_af, price_cents, offered_on,"
    " status, delivered_af, note"
)


def _lease_from(row: sqlite3.Row) -> Lease:
    return Lease(
        number=text_value(row["number"], "lease.number"),
        water_year=int_value(row["water_year"], "lease.water_year"),
        lessor=AccountNumber(int_value(row["lessor"], "lease.lessor")),
        lessee=AccountNumber(int_value(row["lessee"], "lease.lessee")),
        source=text_enum(LeaseSource, row["source"], "lease.source"),
        volume_af=text_decimal(row["volume_af"], "lease.volume_af"),
        price=Money(int_value(row["price_cents"], "lease.price_cents")),
        offered_on=text_date(row["offered_on"], "lease.offered_on"),
        status=text_enum(LeaseStatus, row["status"], "lease.status"),
        delivered_af=text_decimal(row["delivered_af"], "lease.delivered_af"),
        note=text_value(row["note"], "lease.note"),
    )


def offer(connection: sqlite3.Connection, lease: Lease) -> None:
    """Write a new lease. The same number twice is a conflict."""

    existing = one(connection, "SELECT number FROM lease WHERE number = ?", (lease.number,))
    if existing is not None:
        raise ConflictError(f"lease {lease.number} is already in the book")
    with transaction(connection):
        connection.execute(
            f"INSERT INTO lease ({LEASE_COLUMNS}) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                lease.number,
                lease.water_year,
                lease.lessor.number,
                lease.lessee.number,
                enum_text(lease.source),
                decimal_text(lease.volume_af),
                lease.price.cents,
                date_text(lease.offered_on),
                enum_text(lease.status),
                decimal_text(lease.delivered_af),
                lease.note,
            ),
        )


def save_lease(connection: sqlite3.Connection, lease: Lease) -> None:
    """Write where a lease has got to and what it has delivered."""

    load_lease(connection, lease.number)
    with transaction(connection):
        connection.execute(
            "UPDATE lease SET status = ?, delivered_af = ?, note = ? WHERE number = ?",
            (
                enum_text(lease.status),
                decimal_text(lease.delivered_af),
                lease.note,
                lease.number,
            ),
        )


def load_lease(connection: sqlite3.Connection, number: str) -> Lease:
    row = one(connection, f"SELECT {LEASE_COLUMNS} FROM lease WHERE number = ?", (number,))
    if row is None:
        raise NotFoundError("lease", number)
    return _lease_from(row)


def load_book(connection: sqlite3.Connection, water_year: int) -> LeaseBook:
    rows = query(
        connection,
        f"SELECT {LEASE_COLUMNS} FROM lease WHERE water_year = ? ORDER BY number",
        (water_year,),
    )
    return LeaseBook(water_year=water_year, leases=tuple(_lease_from(row) for row in rows))


def leases_for(
    connection: sqlite3.Connection, account: AccountNumber, water_year: int
) -> tuple[Lease, ...]:
    """Every lease an account is on either side of."""

    rows = query(
        connection,
        f"SELECT {LEASE_COLUMNS} FROM lease WHERE water_year = ?"
        " AND (lessor = ? OR lessee = ?) ORDER BY number",
        (water_year, account.number, account.number),
    )
    return tuple(_lease_from(row) for row in rows)


def net_leased(connection: sqlite3.Connection, account: AccountNumber, water_year: int) -> Decimal:
    """What an account has gained or given up this year, on net."""

    return load_book(connection, water_year).net_for(account)
