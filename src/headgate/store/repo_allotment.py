"""Reading and writing the allotment.

Every revision is kept. The board raising the allotment in May and cutting it
in August is three rows, not one changed row, because an irrigator who ordered
against the May number has a fair argument about the August one and the book
has to be able to show him what he was told.

What each account has used is a running total and it does change, which is the
one thing here that is not append only. It cannot be otherwise: the use is a
sum of deliveries and the deliveries are already in the journal.
"""

from __future__ import annotations

import sqlite3
from datetime import date
from decimal import Decimal

from ..duty.allotment import Allotment, AllotmentLedger, AllotmentUse
from ..errors import ConflictError, NotFoundError
from ..ids import AccountNumber
from .db import one, query, transaction
from .serial import date_text, decimal_text, int_value, text_date, text_decimal, text_value

ALLOTMENT_COLUMNS = "water_year, revision, af_per_share, set_on, basis"
USE_COLUMNS = "water_year, account_number, shares, used_af"


def set_allotment(connection: sqlite3.Connection, allotment: Allotment) -> None:
    """Write a revision. The same revision twice is a conflict."""

    existing = one(
        connection,
        "SELECT revision FROM allotment WHERE water_year = ? AND revision = ?",
        (allotment.water_year, allotment.revision),
    )
    if existing is not None:
        raise ConflictError(
            f"revision {allotment.revision} of the {allotment.water_year} allotment is "
            "already written"
        )
    with transaction(connection):
        connection.execute(
            f"INSERT INTO allotment ({ALLOTMENT_COLUMNS}) VALUES (?, ?, ?, ?, ?)",
            (
                allotment.water_year,
                allotment.revision,
                decimal_text(allotment.af_per_share),
                date_text(allotment.set_on),
                allotment.basis,
            ),
        )


def _allotment_from(row: sqlite3.Row) -> Allotment:
    return Allotment(
        water_year=int_value(row["water_year"], "allotment.water_year"),
        af_per_share=text_decimal(row["af_per_share"], "allotment.af_per_share"),
        set_on=text_date(row["set_on"], "allotment.set_on"),
        basis=text_value(row["basis"], "allotment.basis"),
        revision=int_value(row["revision"], "allotment.revision"),
    )


def current_allotment(connection: sqlite3.Connection, water_year: int) -> Allotment:
    """The revision that stands, which is the last one written."""

    rows = query(
        connection,
        f"SELECT {ALLOTMENT_COLUMNS} FROM allotment WHERE water_year = ?"
        " ORDER BY revision DESC LIMIT 1",
        (water_year,),
    )
    if not rows:
        raise NotFoundError("allotment", str(water_year))
    return _allotment_from(rows[0])


def allotment_on(connection: sqlite3.Connection, water_year: int, day: date) -> Allotment:
    """The revision that stood on a day, which is what an order was answered against."""

    rows = query(
        connection,
        f"SELECT {ALLOTMENT_COLUMNS} FROM allotment WHERE water_year = ? AND set_on <= ?"
        " ORDER BY revision DESC LIMIT 1",
        (water_year, date_text(day)),
    )
    if not rows:
        raise NotFoundError("allotment", f"{water_year} on {day}")
    return _allotment_from(rows[0])


def revisions(connection: sqlite3.Connection, water_year: int) -> tuple[Allotment, ...]:
    rows = query(
        connection,
        f"SELECT {ALLOTMENT_COLUMNS} FROM allotment WHERE water_year = ? ORDER BY revision",
        (water_year,),
    )
    return tuple(_allotment_from(row) for row in rows)


def save_ledger(connection: sqlite3.Connection, ledger: AllotmentLedger) -> None:
    """Write what every account holds and has used this year."""

    with transaction(connection):
        for use in ledger.uses:
            connection.execute(
                f"INSERT INTO allotment_use ({USE_COLUMNS}) VALUES (?, ?, ?, ?)"
                " ON CONFLICT (water_year, account_number) DO UPDATE SET"
                " shares = excluded.shares, used_af = excluded.used_af",
                (
                    ledger.allotment.water_year,
                    use.account.number,
                    decimal_text(use.shares),
                    decimal_text(use.used_af),
                ),
            )


def load_ledger(connection: sqlite3.Connection, water_year: int) -> AllotmentLedger:
    allotment = current_allotment(connection, water_year)
    rows = query(
        connection,
        f"SELECT {USE_COLUMNS} FROM allotment_use WHERE water_year = ? ORDER BY account_number",
        (water_year,),
    )
    return AllotmentLedger(
        allotment=allotment,
        uses=tuple(
            AllotmentUse(
                account=AccountNumber(
                    int_value(row["account_number"], "allotment_use.account_number")
                ),
                shares=text_decimal(row["shares"], "allotment_use.shares"),
                used_af=text_decimal(row["used_af"], "allotment_use.used_af"),
            )
            for row in rows
        ),
    )


def used_by(connection: sqlite3.Connection, account: AccountNumber, water_year: int) -> Decimal:
    row = one(
        connection,
        "SELECT used_af FROM allotment_use WHERE water_year = ? AND account_number = ?",
        (water_year, account.number),
    )
    if row is None:
        raise NotFoundError("allotment account", f"{account} in {water_year}")
    return text_decimal(row["used_af"], "allotment_use.used_af")
