import sqlite3
from datetime import date, datetime
from decimal import Decimal

import pytest

from headgate.errors import NotFoundError
from headgate.ids import AccountNumber, DitchCode, TurnoutCode
from headgate.model.account import Account, AccountStatus, ShareRegister
from headgate.model.ditch import Ditch, DitchSystem, Turnout
from headgate.model.order import OrderStatus, WaterOrder
from headgate.store.repo_accounts import save_register
from headgate.store.repo_ditch import save_system
from headgate.store.repo_orders import (
    load_book,
    load_order,
    next_order_number,
    orders_for_account,
    orders_running_at,
    save_order,
    waiting_orders,
)
from headgate.wateryear import Span

TURNOUT = TurnoutCode("L2-14")
OTHER = TurnoutCode("L2-20")


def stocked(book: sqlite3.Connection) -> None:
    save_system(
        book,
        DitchSystem(
            ditches=(
                Ditch(
                    code=DitchCode("L2"),
                    name="Second Lateral",
                    capacity_cfs=Decimal("12"),
                    length_feet=Decimal("10560"),
                    loss_fraction_per_mile=Decimal("0.05"),
                    turnouts=(
                        Turnout(
                            TURNOUT, "Bench gate", Decimal("5280"), Decimal("6"), Decimal("40")
                        ),
                        Turnout(OTHER, "Lower gate", Decimal("9000"), Decimal("6"), Decimal("60")),
                    ),
                    diversion_mile=Decimal("28.4"),
                ),
            )
        ),
    )
    save_register(
        book,
        ShareRegister(
            accounts=(
                Account(AccountNumber(118), "Holder 118", date(1994, 3, 1), AccountStatus.ACTIVE),
                Account(AccountNumber(212), "Holder 212", date(1998, 5, 1), AccountStatus.ACTIVE),
            )
        ),
    )


def order(
    order_id: int = 1,
    account: int = 118,
    turnout: TurnoutCode = TURNOUT,
    first_day: int = 1,
    last_day: int = 4,
) -> WaterOrder:
    return WaterOrder(
        order_id=order_id,
        account=AccountNumber(account),
        turnout=turnout,
        requested_cfs=Decimal("3"),
        span=Span(datetime(2025, 7, first_day, 6), datetime(2025, 7, last_day, 6)),
        placed_at=datetime(2025, 6, 28, 8),
    )


def test_an_order_comes_back_the_way_it_went_in(book: sqlite3.Connection) -> None:
    stocked(book)
    save_order(book, order())
    assert load_order(book, 1) == order()


def test_answering_an_order_updates_the_row(book: sqlite3.Connection) -> None:
    stocked(book)
    save_order(book, order())
    save_order(book, order().accept(Decimal("2"), "lateral was full"))
    loaded = load_order(book, 1)
    assert loaded.status is OrderStatus.REDUCED
    assert loaded.allowed_cfs == Decimal("2")
    assert loaded.requested_cfs == Decimal("3")


def test_an_order_that_is_not_there_is_reported_missing(book: sqlite3.Connection) -> None:
    with pytest.raises(NotFoundError, match="no order"):
        load_order(book, 9)


def test_the_next_order_number_follows_the_highest(book: sqlite3.Connection) -> None:
    stocked(book)
    assert next_order_number(book) == 1
    save_order(book, order(order_id=7))
    assert next_order_number(book) == 8


def test_the_whole_book_comes_back_in_order(book: sqlite3.Connection) -> None:
    stocked(book)
    save_order(book, order(order_id=2))
    save_order(book, order(order_id=1))
    assert [item.order_id for item in load_book(book).orders] == [1, 2]


def test_a_span_pulls_only_the_orders_that_touch_it(book: sqlite3.Connection) -> None:
    stocked(book)
    save_order(book, order(order_id=1, first_day=1, last_day=4))
    save_order(book, order(order_id=2, first_day=10, last_day=12))
    span = Span(datetime(2025, 7, 3, 6), datetime(2025, 7, 6, 6))
    assert [item.order_id for item in load_book(book, span).orders] == [1]


def test_orders_for_an_account_come_back_in_run_order(book: sqlite3.Connection) -> None:
    stocked(book)
    save_order(book, order(order_id=1, first_day=10, last_day=12))
    save_order(book, order(order_id=2, first_day=1, last_day=4))
    save_order(book, order(order_id=3, account=212))
    found = orders_for_account(book, AccountNumber(118))
    assert [item.order_id for item in found] == [2, 1]


def test_only_answered_orders_are_running(book: sqlite3.Connection) -> None:
    stocked(book)
    save_order(book, order(order_id=1).accept(Decimal("3")))
    save_order(book, order(order_id=2, turnout=OTHER))
    running = orders_running_at(book, datetime(2025, 7, 2, 12))
    assert [item.order_id for item in running] == [1]


def test_a_cancelled_order_is_not_running(book: sqlite3.Connection) -> None:
    stocked(book)
    save_order(book, order(order_id=1).accept(Decimal("3")).cancel("rained"))
    assert orders_running_at(book, datetime(2025, 7, 2, 12)) == ()


def test_the_orders_still_waiting_come_back_oldest_first(book: sqlite3.Connection) -> None:
    stocked(book)
    save_order(book, order(order_id=1))
    save_order(book, order(order_id=2).accept(Decimal("3")))
    assert [item.order_id for item in waiting_orders(book)] == [1]


def test_an_order_for_a_turnout_that_is_not_there_is_refused(book: sqlite3.Connection) -> None:
    stocked(book)
    with pytest.raises(sqlite3.IntegrityError):
        save_order(book, order(turnout=TurnoutCode("L9-1")))
