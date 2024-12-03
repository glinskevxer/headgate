"""Reading and writing the payments.

Payments are never edited. A cheque that bounced is answered by a second row
that takes it back off, the same way everything else in this system corrects
itself, so the account history reads as what happened rather than as what
somebody wishes had happened.
"""

from __future__ import annotations

import sqlite3
from datetime import date

from ..assessment.billing import Bill
from ..assessment.payment import AccountLedger, Payment, PaymentMethod
from ..errors import NotFoundError
from ..ids import AccountNumber
from ..money import Money
from .db import one, query, scalar, transaction
from .repo_bills import bills_for_account
from .serial import date_text, enum_text, int_value, text_date, text_enum, text_value

PAYMENT_COLUMNS = "payment_id, account_number, received_on, amount_cents, method, reference"


def _payment_from(row: sqlite3.Row) -> Payment:
    return Payment(
        account=AccountNumber(int_value(row["account_number"], "payment.account_number")),
        received_on=text_date(row["received_on"], "payment.received_on"),
        amount=Money(int_value(row["amount_cents"], "payment.amount_cents")),
        method=text_enum(PaymentMethod, row["method"], "payment.method"),
        reference=text_value(row["reference"], "payment.reference"),
    )


def next_payment_number(connection: sqlite3.Connection) -> int:
    highest = scalar(connection, "SELECT max(payment_id) FROM payment")
    return 1 if highest is None else int(highest) + 1


def take_payment(connection: sqlite3.Connection, payment: Payment) -> int:
    """Write a payment and hand back the number it was given."""

    with transaction(connection):
        payment_id = next_payment_number(connection)
        connection.execute(
            f"INSERT INTO payment ({PAYMENT_COLUMNS}) VALUES (?, ?, ?, ?, ?, ?)",
            (
                payment_id,
                payment.account.number,
                date_text(payment.received_on),
                payment.amount.cents,
                enum_text(payment.method),
                payment.reference,
            ),
        )
    return payment_id


def load_payment(connection: sqlite3.Connection, payment_id: int) -> Payment:
    row = one(
        connection, f"SELECT {PAYMENT_COLUMNS} FROM payment WHERE payment_id = ?", (payment_id,)
    )
    if row is None:
        raise NotFoundError("payment", str(payment_id))
    return _payment_from(row)


def payments_for(connection: sqlite3.Connection, account: AccountNumber) -> tuple[Payment, ...]:
    rows = query(
        connection,
        f"SELECT {PAYMENT_COLUMNS} FROM payment WHERE account_number = ?"
        " ORDER BY received_on, payment_id",
        (account.number,),
    )
    return tuple(_payment_from(row) for row in rows)


def taken_between(connection: sqlite3.Connection, first: date, last: date) -> tuple[Payment, ...]:
    rows = query(
        connection,
        f"SELECT {PAYMENT_COLUMNS} FROM payment WHERE received_on >= ? AND received_on < ?"
        " ORDER BY received_on, payment_id",
        (date_text(first), date_text(last)),
    )
    return tuple(_payment_from(row) for row in rows)


def account_ledger(connection: sqlite3.Connection, account: AccountNumber) -> AccountLedger:
    """The account's bills and payments together, which is what a clerk wants."""

    bills: tuple[Bill, ...] = bills_for_account(connection, account)
    return AccountLedger(account=account, bills=bills, payments=payments_for(connection, account))


def taken_total(connection: sqlite3.Connection, first: date, last: date) -> Money:
    """What came in over a stretch, for the treasurer's report."""

    total = Money.zero()
    for payment in taken_between(connection, first, last):
        total = total + payment.amount
    return total
