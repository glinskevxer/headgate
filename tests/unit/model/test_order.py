from datetime import datetime
from decimal import Decimal

import pytest

from headgate.errors import NotFoundError, PolicyError, ValidationError
from headgate.ids import AccountNumber, TurnoutCode
from headgate.model.order import OrderBook, OrderStatus, WaterOrder
from headgate.wateryear import Span

TURNOUT = TurnoutCode("L2-14")
OTHER = TurnoutCode("L2-20")
PLACED = datetime(2025, 6, 30, 8)


def order(
    order_id: int = 1,
    rate: str = "3",
    first_day: int = 1,
    last_day: int = 4,
    account: int = 118,
    turnout: TurnoutCode = TURNOUT,
) -> WaterOrder:
    return WaterOrder(
        order_id=order_id,
        account=AccountNumber(account),
        turnout=turnout,
        requested_cfs=Decimal(rate),
        span=Span(datetime(2025, 7, first_day, 6), datetime(2025, 7, last_day, 6)),
        placed_at=PLACED,
    )


def test_an_order_number_starts_at_one() -> None:
    with pytest.raises(ValidationError, match="not an order number"):
        order(order_id=0)


def test_an_order_asks_for_water() -> None:
    with pytest.raises(ValidationError, match="asks for no water"):
        order(rate="0")


def test_an_order_placed_after_the_run_is_refused() -> None:
    with pytest.raises(ValidationError, match="after the water was due"):
        WaterOrder(
            order_id=1,
            account=AccountNumber(118),
            turnout=TURNOUT,
            requested_cfs=Decimal("3"),
            span=Span(datetime(2025, 7, 1, 6), datetime(2025, 7, 4, 6)),
            placed_at=datetime(2025, 7, 2, 6),
        )


def test_an_order_reports_how_much_notice_it_gave() -> None:
    assert order().notice_hours == Decimal("22.00")


def test_a_requested_order_runs_nothing_yet() -> None:
    assert order().running_cfs == Decimal("0")
    assert order().volume_af == Decimal("0")


def test_accepting_at_the_rate_asked_for_is_an_acceptance() -> None:
    answered = order().accept(Decimal("3"))
    assert answered.status is OrderStatus.ACCEPTED
    assert answered.running_cfs == Decimal("3")
    assert answered.volume_af > Decimal("0")


def test_accepting_at_less_is_a_reduction() -> None:
    answered = order().accept(Decimal("2"), "lateral was full")
    assert answered.status is OrderStatus.REDUCED
    assert answered.allowed_cfs == Decimal("2")
    assert answered.requested_cfs == Decimal("3")
    assert answered.note == "lateral was full"


def test_accepting_at_more_than_was_asked_for_gives_what_was_asked() -> None:
    answered = order().accept(Decimal("8"))
    assert answered.allowed_cfs == Decimal("3")
    assert answered.status is OrderStatus.ACCEPTED


def test_accepting_nothing_is_a_refusal() -> None:
    answered = order().accept(Decimal("0"))
    assert answered.status is OrderStatus.REFUSED
    assert answered.running_cfs == Decimal("0")


def test_an_order_is_answered_once() -> None:
    answered = order().accept(Decimal("3"))
    with pytest.raises(PolicyError, match="already been answered"):
        answered.accept(Decimal("2"))
    with pytest.raises(PolicyError, match="already been answered"):
        answered.refuse("too late")


def test_an_order_can_be_cancelled_until_it_is_settled() -> None:
    cancelled = order().accept(Decimal("3")).cancel("rained")
    assert cancelled.status is OrderStatus.CANCELLED
    with pytest.raises(PolicyError, match="already cancelled"):
        cancelled.cancel()


def test_only_an_order_that_ran_can_be_delivered() -> None:
    assert order().accept(Decimal("3")).mark_delivered().status is OrderStatus.DELIVERED
    with pytest.raises(PolicyError, match="never ran"):
        order().refuse("no water").mark_delivered()


def test_an_accepted_order_needs_a_rate_on_it() -> None:
    with pytest.raises(ValidationError, match="no stated rate"):
        WaterOrder(
            order_id=1,
            account=AccountNumber(118),
            turnout=TURNOUT,
            requested_cfs=Decimal("3"),
            span=Span(datetime(2025, 7, 1, 6), datetime(2025, 7, 4, 6)),
            placed_at=PLACED,
            status=OrderStatus.ACCEPTED,
        )


def test_the_book_refuses_the_same_number_twice() -> None:
    with pytest.raises(ValidationError, match="appears twice"):
        OrderBook(orders=(order(1), order(1)))


def test_the_book_hands_out_the_next_number() -> None:
    assert OrderBook().next_number == 1
    assert OrderBook(orders=(order(1), order(4))).next_number == 5


def test_an_order_can_be_looked_up_and_replaced() -> None:
    book = OrderBook(orders=(order(1),))
    answered = book.order(1).accept(Decimal("3"))
    updated = book.replace_order(answered)
    assert updated.order(1).status is OrderStatus.ACCEPTED
    with pytest.raises(NotFoundError, match="no order"):
        book.order(9)


def test_orders_are_listed_by_turnout_and_by_account() -> None:
    book = OrderBook(orders=(order(1), order(2, turnout=OTHER, account=212)))
    assert len(book.for_turnout(TURNOUT)) == 1
    assert len(book.for_account(AccountNumber(212))) == 1


def test_the_orders_running_at_a_moment_are_the_answered_ones() -> None:
    book = OrderBook(orders=(order(1).accept(Decimal("3")), order(2, turnout=OTHER)))
    running = book.running_at(datetime(2025, 7, 2, 12))
    assert [item.order_id for item in running] == [1]


def test_the_ordered_rate_at_a_turnout_adds_up_what_is_running() -> None:
    book = OrderBook(
        orders=(order(1).accept(Decimal("3")), order(2, rate="2").accept(Decimal("2")))
    )
    assert book.ordered_rate_at(TURNOUT, datetime(2025, 7, 2, 12)) == Decimal("5")


def test_overlapping_orders_at_a_turnout_are_found() -> None:
    book = OrderBook(orders=(order(1), order(2, first_day=5, last_day=8)))
    clash = book.overlapping(TURNOUT, Span(datetime(2025, 7, 3, 6), datetime(2025, 7, 6, 6)))
    assert [item.order_id for item in clash] == [1, 2]


def test_a_settled_order_does_not_clash_with_anything() -> None:
    book = OrderBook(orders=(order(1).cancel(),))
    clash = book.overlapping(TURNOUT, Span(datetime(2025, 7, 1, 6), datetime(2025, 7, 4, 6)))
    assert clash == ()


def test_the_orders_still_waiting_are_listed() -> None:
    book = OrderBook(orders=(order(1), order(2).accept(Decimal("3"))))
    assert [item.order_id for item in book.waiting()] == [1]
