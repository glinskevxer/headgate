"""Reading and writing the order book.

An order row is updated in place when the office answers it, because the answer
is a state of the same order rather than a new one. What is never overwritten is
the rate that was asked for, which is why the request and the allowance are
separate columns.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime

from ..errors import NotFoundError
from ..ids import AccountNumber, TurnoutCode
from ..model.order import OrderBook, OrderStatus, WaterOrder
from ..wateryear import Span
from .db import one, query, scalar, transaction
from .serial import (
    decimal_text,
    enum_text,
    instant_text,
    int_value,
    optional_decimal,
    text_decimal,
    text_enum,
    text_instant,
    text_value,
)

ORDER_COLUMNS = (
    "order_id, account_number, turnout_code, requested_cfs, run_from, run_to,"
    " placed_at, status, allowed_cfs, note"
)


def _order_from(row: sqlite3.Row) -> WaterOrder:
    return WaterOrder(
        order_id=int_value(row["order_id"], "water_order.order_id"),
        account=AccountNumber(int_value(row["account_number"], "water_order.account_number")),
        turnout=TurnoutCode(text_value(row["turnout_code"], "water_order.turnout_code")),
        requested_cfs=text_decimal(row["requested_cfs"], "water_order.requested_cfs"),
        span=Span(
            text_instant(row["run_from"], "water_order.run_from"),
            text_instant(row["run_to"], "water_order.run_to"),
        ),
        placed_at=text_instant(row["placed_at"], "water_order.placed_at"),
        status=text_enum(OrderStatus, row["status"], "water_order.status"),
        allowed_cfs=optional_decimal(row["allowed_cfs"], "water_order.allowed_cfs"),
        note=text_value(row["note"], "water_order.note"),
    )


def save_order(connection: sqlite3.Connection, order: WaterOrder) -> None:
    """Write an order, or the answer that came back on one already there."""

    with transaction(connection):
        connection.execute(
            f"INSERT INTO water_order ({ORDER_COLUMNS}) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"
            " ON CONFLICT (order_id) DO UPDATE SET"
            " status = excluded.status, allowed_cfs = excluded.allowed_cfs,"
            " note = excluded.note",
            (
                order.order_id,
                order.account.number,
                str(order.turnout),
                decimal_text(order.requested_cfs),
                instant_text(order.span.start),
                instant_text(order.span.end),
                instant_text(order.placed_at),
                enum_text(order.status),
                decimal_text(order.allowed_cfs) if order.allowed_cfs is not None else None,
                order.note,
            ),
        )


def load_order(connection: sqlite3.Connection, order_id: int) -> WaterOrder:
    row = one(
        connection, f"SELECT {ORDER_COLUMNS} FROM water_order WHERE order_id = ?", (order_id,)
    )
    if row is None:
        raise NotFoundError("order", str(order_id))
    return _order_from(row)


def load_book(connection: sqlite3.Connection, span: Span | None = None) -> OrderBook:
    """The order book, or the part of it that touches a span."""

    if span is None:
        rows = query(connection, f"SELECT {ORDER_COLUMNS} FROM water_order ORDER BY order_id")
    else:
        rows = query(
            connection,
            f"SELECT {ORDER_COLUMNS} FROM water_order WHERE run_from < ? AND run_to > ?"
            " ORDER BY order_id",
            (instant_text(span.end), instant_text(span.start)),
        )
    return OrderBook(orders=tuple(_order_from(row) for row in rows))


def next_order_number(connection: sqlite3.Connection) -> int:
    highest = scalar(connection, "SELECT max(order_id) FROM water_order")
    return 1 if highest is None else int(highest) + 1


def orders_for_account(
    connection: sqlite3.Connection, account: AccountNumber
) -> tuple[WaterOrder, ...]:
    rows = query(
        connection,
        f"SELECT {ORDER_COLUMNS} FROM water_order WHERE account_number = ? ORDER BY run_from",
        (account.number,),
    )
    return tuple(_order_from(row) for row in rows)


def orders_running_at(connection: sqlite3.Connection, moment: datetime) -> tuple[WaterOrder, ...]:
    rows = query(
        connection,
        f"SELECT {ORDER_COLUMNS} FROM water_order WHERE run_from <= ? AND run_to > ?"
        " AND status IN ('accepted', 'reduced') ORDER BY turnout_code",
        (instant_text(moment), instant_text(moment)),
    )
    return tuple(_order_from(row) for row in rows)


def waiting_orders(connection: sqlite3.Connection) -> tuple[WaterOrder, ...]:
    rows = query(
        connection,
        f"SELECT {ORDER_COLUMNS} FROM water_order WHERE status = 'requested' ORDER BY placed_at",
    )
    return tuple(_order_from(row) for row in rows)
