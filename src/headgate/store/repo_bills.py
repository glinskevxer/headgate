"""Reading and writing the assessment bills.

A bill and its lines go in together and never come out again. A bill that was
wrong is answered by a reversing bill that points at it, the same way the
journal answers a wrong entry, so the account's history reads as three
documents rather than as one document that changed its mind.
"""

from __future__ import annotations

import sqlite3
from datetime import date

from ..assessment.billing import Bill, BillRun, ChargeKind, Line
from ..errors import NotFoundError, PolicyError
from ..ids import AccountNumber
from ..money import Money
from .db import one, query, scalar, transaction
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

BILL_COLUMNS = "bill_id, water_year, account_number, issued_on, reverses_bill_id, note"
LINE_COLUMNS = "bill_id, line_number, kind, description, quantity, amount_cents"


def _lines_for(connection: sqlite3.Connection, bill_id: int) -> tuple[Line, ...]:
    rows = query(
        connection,
        f"SELECT {LINE_COLUMNS} FROM assessment_line WHERE bill_id = ? ORDER BY line_number",
        (bill_id,),
    )
    return tuple(
        Line(
            kind=text_enum(ChargeKind, row["kind"], "assessment_line.kind"),
            description=text_value(row["description"], "assessment_line.description"),
            quantity=text_decimal(row["quantity"], "assessment_line.quantity"),
            amount=Money(int_value(row["amount_cents"], "assessment_line.amount_cents")),
        )
        for row in rows
    )


def _bill_from(connection: sqlite3.Connection, row: sqlite3.Row) -> Bill:
    bill_id = int_value(row["bill_id"], "assessment_bill.bill_id")
    return Bill(
        account=AccountNumber(int_value(row["account_number"], "assessment_bill.account_number")),
        water_year=int_value(row["water_year"], "assessment_bill.water_year"),
        issued_on=text_date(row["issued_on"], "assessment_bill.issued_on"),
        lines=_lines_for(connection, bill_id),
    )


def next_bill_number(connection: sqlite3.Connection) -> int:
    highest = scalar(connection, "SELECT max(bill_id) FROM assessment_bill")
    return 1 if highest is None else int(highest) + 1


def save_bill(
    connection: sqlite3.Connection,
    bill: Bill,
    note: str = "",
    reverses: int | None = None,
) -> int:
    """Write a bill and its lines, and hand back the number it was given."""

    if not bill.lines:
        raise PolicyError(f"the {bill.water_year} bill for {bill.account} has no lines on it")
    with transaction(connection):
        bill_id = next_bill_number(connection)
        connection.execute(
            f"INSERT INTO assessment_bill ({BILL_COLUMNS}) VALUES (?, ?, ?, ?, ?, ?)",
            (
                bill_id,
                bill.water_year,
                bill.account.number,
                date_text(bill.issued_on),
                reverses,
                note,
            ),
        )
        for number, line in enumerate(bill.lines, start=1):
            connection.execute(
                f"INSERT INTO assessment_line ({LINE_COLUMNS}) VALUES (?, ?, ?, ?, ?, ?)",
                (
                    bill_id,
                    number,
                    enum_text(line.kind),
                    line.description,
                    decimal_text(line.quantity),
                    line.amount.cents,
                ),
            )
    return bill_id


def load_bill(connection: sqlite3.Connection, bill_id: int) -> Bill:
    row = one(
        connection, f"SELECT {BILL_COLUMNS} FROM assessment_bill WHERE bill_id = ?", (bill_id,)
    )
    if row is None:
        raise NotFoundError("bill", str(bill_id))
    return _bill_from(connection, row)


def save_run(connection: sqlite3.Connection, run: BillRun, note: str = "") -> tuple[int, ...]:
    """Write a whole season's run, in account order."""

    return tuple(save_bill(connection, bill, note) for bill in run.bills)


def load_run(connection: sqlite3.Connection, water_year: int) -> BillRun:
    rows = query(
        connection,
        f"SELECT {BILL_COLUMNS} FROM assessment_bill WHERE water_year = ?"
        " AND reverses_bill_id IS NULL ORDER BY account_number",
        (water_year,),
    )
    if not rows:
        raise NotFoundError("bill run", str(water_year))
    issued = text_date(rows[0]["issued_on"], "assessment_bill.issued_on")
    return BillRun(
        water_year=water_year,
        issued_on=issued,
        bills=tuple(_bill_from(connection, row) for row in rows),
    )


def bills_for_account(connection: sqlite3.Connection, account: AccountNumber) -> tuple[Bill, ...]:
    rows = query(
        connection,
        f"SELECT {BILL_COLUMNS} FROM assessment_bill WHERE account_number = ?"
        " ORDER BY water_year, bill_id",
        (account.number,),
    )
    return tuple(_bill_from(connection, row) for row in rows)


def balance_for(
    connection: sqlite3.Connection, account: AccountNumber, water_year: int | None = None
) -> Money:
    """What an account owes, counting every bill written against it."""

    total = Money.zero()
    for bill in bills_for_account(connection, account):
        if water_year is None or bill.water_year == water_year:
            total = total + bill.total
    return total


def issued_on(connection: sqlite3.Connection, water_year: int) -> date | None:
    row = one(
        connection,
        "SELECT min(issued_on) AS first FROM assessment_bill WHERE water_year = ?",
        (water_year,),
    )
    if row is None or row["first"] is None:
        return None
    return text_date(row["first"], "assessment_bill.issued_on")
