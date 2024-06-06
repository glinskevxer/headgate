from datetime import date, datetime
from decimal import Decimal

import pytest

from headgate.errors import PolicyError
from headgate.ids import AccountNumber, DitchCode, TurnoutCode
from headgate.model.account import Account, AccountStatus, ShareCertificate, ShareRegister
from headgate.model.ditch import Ditch, DitchSystem, Turnout
from headgate.model.order import OrderBook, OrderStatus, WaterOrder
from headgate.orders.intake import IntakeRules, answer_order, binding_limit, receive
from headgate.wateryear import IrrigationSeason, Span

TURNOUT = TurnoutCode("L2-14")
PLACED = datetime(2025, 6, 28, 8)


def system(turnout_capacity: str = "6", lateral_capacity: str = "12") -> DitchSystem:
    main = Ditch(
        code=DitchCode("MAIN"),
        name="Sanpete Main Canal",
        capacity_cfs=Decimal("48"),
        length_feet=Decimal("26400"),
        loss_fraction_per_mile=Decimal("0.02"),
        diversion_mile=Decimal("28.4"),
    )
    lateral = Ditch(
        code=DitchCode("L2"),
        name="Second Lateral",
        capacity_cfs=Decimal(lateral_capacity),
        length_feet=Decimal("10560"),
        loss_fraction_per_mile=Decimal("0.05"),
        turnouts=(
            Turnout(
                TURNOUT, "Bench gate", Decimal("5280"), Decimal(turnout_capacity), Decimal("40")
            ),
        ),
        parent=DitchCode("MAIN"),
        offtake_station_feet=Decimal("15840"),
    )
    return DitchSystem(ditches=(main, lateral))


def register(shares: str = "20", status: AccountStatus = AccountStatus.ACTIVE) -> ShareRegister:
    return ShareRegister(
        accounts=(Account(AccountNumber(118), "Holder 118", date(1994, 3, 1), status),),
        certificates=(
            ShareCertificate(
                "A-1001", AccountNumber(118), Decimal(shares), TURNOUT, date(2020, 4, 1)
            ),
        ),
    )


def order(rate: str = "3", order_id: int = 1, placed: datetime = PLACED) -> WaterOrder:
    return WaterOrder(
        order_id=order_id,
        account=AccountNumber(118),
        turnout=TURNOUT,
        requested_cfs=Decimal(rate),
        span=Span(datetime(2025, 7, 1, 6), datetime(2025, 7, 4, 6)),
        placed_at=placed,
    )


def season() -> IrrigationSeason:
    return IrrigationSeason.default_for(2025)


def answer(
    the_order: WaterOrder | None = None,
    rules: IntakeRules | None = None,
    book: OrderBook | None = None,
    shares: str = "20",
    status: AccountStatus = AccountStatus.ACTIVE,
    curtailed_to: Decimal | None = None,
    ditch: DitchSystem | None = None,
) -> WaterOrder:
    return answer_order(
        the_order or order(),
        rules or IntakeRules(),
        register(shares, status),
        season(),
        ditch or system(),
        book or OrderBook(),
        curtailed_to,
    )


def test_an_ordinary_order_is_accepted_as_ordered() -> None:
    answered = answer()
    assert answered.status is OrderStatus.ACCEPTED
    assert answered.allowed_cfs == Decimal("3")
    assert answered.note == "as ordered"


def test_a_suspended_account_is_refused_rather_than_reduced() -> None:
    answered = answer(status=AccountStatus.SUSPENDED)
    assert answered.status is OrderStatus.REFUSED
    assert "suspended" in answered.note


def test_short_notice_is_refused() -> None:
    answered = answer(order(placed=datetime(2025, 6, 30, 20)))
    assert answered.status is OrderStatus.REFUSED
    assert "notice" in answered.note


def test_short_notice_can_be_allowed_when_the_district_says_so() -> None:
    answered = answer(
        order(placed=datetime(2025, 6, 30, 20)), rules=IntakeRules(allow_short_notice=True)
    )
    assert answered.status is OrderStatus.ACCEPTED


def test_an_order_outside_the_season_is_refused() -> None:
    winter = WaterOrder(
        order_id=1,
        account=AccountNumber(118),
        turnout=TURNOUT,
        requested_cfs=Decimal("3"),
        span=Span(datetime(2025, 3, 1, 6), datetime(2025, 3, 4, 6)),
        placed_at=datetime(2025, 2, 20, 8),
    )
    answered = answer(winter)
    assert answered.status is OrderStatus.REFUSED
    assert "season" in answered.note


def test_an_order_running_past_the_close_is_refused() -> None:
    late = WaterOrder(
        order_id=1,
        account=AccountNumber(118),
        turnout=TURNOUT,
        requested_cfs=Decimal("3"),
        span=Span(datetime(2025, 9, 29, 6), datetime(2025, 10, 4, 6)),
        placed_at=datetime(2025, 9, 20, 8),
    )
    answered = answer(late)
    assert answered.status is OrderStatus.REFUSED
    assert "after the season closes" in answered.note


def test_the_shares_behind_a_turnout_cap_the_rate() -> None:
    answered = answer(order(rate="6"), shares="8")
    assert answered.status is OrderStatus.REDUCED
    assert answered.allowed_cfs == Decimal("2")
    assert "shares" in answered.note


def test_the_turnout_caps_the_rate() -> None:
    answered = answer(order(rate="8"), ditch=system(turnout_capacity="4"))
    assert answered.allowed_cfs == Decimal("4")
    assert "passes" in answered.note


def test_orders_already_answered_use_up_the_lateral() -> None:
    book = OrderBook(orders=(order(rate="10", order_id=9).accept(Decimal("10")),))
    answered = answer(order(rate="6"), book=book, ditch=system(turnout_capacity="12"))
    assert answered.allowed_cfs == Decimal("2")
    assert "left over orders" in answered.note


def test_a_full_lateral_refuses_the_order_outright() -> None:
    book = OrderBook(orders=(order(rate="12", order_id=9).accept(Decimal("12")),))
    answered = answer(order(rate="6"), book=book, ditch=system(turnout_capacity="12"))
    assert answered.status is OrderStatus.REFUSED


def test_a_curtailment_holds_the_order_down() -> None:
    answered = answer(order(rate="6"), curtailed_to=Decimal("1.5"))
    assert answered.allowed_cfs == Decimal("1.5")
    assert "curtailment" in answered.note


def test_a_total_curtailment_refuses_the_order() -> None:
    answered = answer(order(rate="6"), curtailed_to=Decimal("0"))
    assert answered.status is OrderStatus.REFUSED
    assert "curtailment" in answered.note


def test_the_smallest_limit_is_the_one_that_binds() -> None:
    answered = answer(order(rate="6"), shares="8", curtailed_to=Decimal("1.5"))
    assert answered.allowed_cfs == Decimal("1.5")


def test_the_binding_limit_can_be_asked_for_on_its_own() -> None:
    limit = binding_limit(
        order(rate="6"), IntakeRules(), register("8"), system(), OrderBook(), None
    )
    assert limit.name == "shares"
    assert limit.rate_cfs == Decimal("2")


def test_receiving_an_order_puts_the_answer_in_the_book() -> None:
    book, answered = receive(OrderBook(), order(), IntakeRules(), register(), season(), system())
    assert book.order(1).status is answered.status
    assert answered.status is OrderStatus.ACCEPTED


def test_the_same_order_number_cannot_be_received_twice() -> None:
    book, _ = receive(OrderBook(), order(), IntakeRules(), register(), season(), system())
    with pytest.raises(PolicyError, match="already in the book"):
        receive(book, order(), IntakeRules(), register(), season(), system())
