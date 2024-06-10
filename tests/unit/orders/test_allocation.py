from datetime import datetime
from decimal import Decimal

import pytest

from headgate.errors import PolicyError, ValidationError
from headgate.ids import AccountNumber, TurnoutCode
from headgate.model.order import WaterOrder
from headgate.orders.allocation import ShortagePolicy, allocate
from headgate.wateryear import Span

FIRST = TurnoutCode("L2-14")
SECOND = TurnoutCode("L2-20")


def order(
    order_id: int,
    rate: str,
    turnout: TurnoutCode = FIRST,
    placed_hour: int = 8,
) -> WaterOrder:
    return WaterOrder(
        order_id=order_id,
        account=AccountNumber(118),
        turnout=turnout,
        requested_cfs=Decimal(rate),
        span=Span(datetime(2025, 7, 1, 6), datetime(2025, 7, 4, 6)),
        placed_at=datetime(2025, 6, 28, placed_hour),
    ).accept(Decimal(rate))


def orders() -> list[WaterOrder]:
    return [order(1, "4"), order(2, "4", SECOND, placed_hour=10), order(3, "2", SECOND, 12)]


def test_plenty_of_water_leaves_every_order_whole() -> None:
    result = allocate(orders(), Decimal("20"))
    assert not result.is_short
    assert result.running_cfs == Decimal("10")


def test_pro_rata_cuts_everybody_by_the_same_fraction() -> None:
    result = allocate(orders(), Decimal("5"))
    assert result.for_order(1).running_cfs == Decimal("2")
    assert result.for_order(3).running_cfs == Decimal("1")
    assert result.is_short


def test_cutting_by_share_follows_the_stock_book() -> None:
    shares = {FIRST: Decimal("30"), SECOND: Decimal("10")}
    result = allocate(orders(), Decimal("5"), ShortagePolicy.BY_SHARE, shares=shares)
    assert result.for_order(1).running_cfs > result.for_order(2).running_cfs


def test_first_ordered_fills_the_early_orders_and_cuts_the_tail() -> None:
    result = allocate(orders(), Decimal("5"), ShortagePolicy.FIRST_ORDERED)
    assert result.for_order(1).running_cfs == Decimal("4")
    assert result.for_order(2).running_cfs == Decimal("1")
    assert result.for_order(3).dropped


def test_an_order_cut_under_the_minimum_head_is_dropped() -> None:
    result = allocate(orders(), Decimal("1"))
    assert result.dropped != ()
    assert all(item.running_cfs == 0 for item in result.dropped)


def test_dropping_an_order_gives_its_water_to_the_others() -> None:
    result = allocate(orders(), Decimal("2"))
    kept = [item for item in result.cuts if not item.dropped]
    assert sum((item.running_cfs for item in kept), Decimal("0")) == Decimal("2")


def test_a_dropped_order_says_why() -> None:
    result = allocate(orders(), Decimal("1"))
    assert "minimum head" in result.dropped[0].reason


def test_the_cut_is_reported_per_order() -> None:
    result = allocate(orders(), Decimal("5"))
    assert result.for_order(1).cut_cfs == Decimal("2")
    assert result.answered_cfs == Decimal("10")


def test_an_unanswered_order_does_not_run() -> None:
    waiting = WaterOrder(
        order_id=9,
        account=AccountNumber(118),
        turnout=FIRST,
        requested_cfs=Decimal("4"),
        span=Span(datetime(2025, 7, 1, 6), datetime(2025, 7, 4, 6)),
        placed_at=datetime(2025, 6, 28, 8),
    )
    result = allocate([*orders(), waiting], Decimal("20"))
    assert len(result.cuts) == 3


def test_a_day_with_no_answered_orders_is_refused() -> None:
    with pytest.raises(PolicyError, match="no answered order"):
        allocate([], Decimal("5"))


def test_a_negative_supply_is_refused() -> None:
    with pytest.raises(ValidationError, match="negative supply"):
        allocate(orders(), Decimal("-1"))


def test_cutting_by_share_without_shares_is_refused() -> None:
    with pytest.raises(PolicyError, match="needs the shares"):
        allocate(orders(), Decimal("5"), ShortagePolicy.BY_SHARE)


def test_a_turnout_with_no_shares_recorded_is_refused() -> None:
    with pytest.raises(PolicyError, match="no shares are recorded"):
        allocate(orders(), Decimal("5"), ShortagePolicy.BY_SHARE, shares={FIRST: Decimal("30")})


def test_asking_about_an_order_that_was_not_allocated_is_refused() -> None:
    result = allocate(orders(), Decimal("20"))
    with pytest.raises(PolicyError, match="not in this allocation"):
        result.for_order(99)


def test_a_dry_ditch_drops_everybody() -> None:
    result = allocate(orders(), Decimal("0"))
    assert len(result.dropped) == 3
    assert result.running_cfs == Decimal("0")


def test_an_order_at_the_minimum_head_is_kept() -> None:
    result = allocate([order(1, "4"), order(2, "1", SECOND)], Decimal("2.5"))
    assert not result.for_order(2).dropped
