from datetime import datetime
from decimal import Decimal

import pytest

from headgate.errors import ValidationError
from headgate.model.stream import Reach, Stream
from headgate.priority.travel import (
    arrival_of,
    carried,
    reaches_in_time,
    release,
    release_needed_for,
    travel_seconds,
)

NOON = datetime(2025, 7, 4, 12)


def stream(loss: str = "0.01") -> Stream:
    return Stream(
        name="Sanpete Creek",
        reaches=(
            Reach("R1", "Upper", Decimal("30"), Decimal("22"), Decimal("2"), Decimal(loss)),
            Reach("R2", "Lower", Decimal("22"), Decimal("14"), Decimal("4"), Decimal(loss)),
        ),
    )


def test_travel_time_rounds_to_the_minute() -> None:
    seconds = travel_seconds(stream(), Decimal("30"), Decimal("22"))
    assert seconds % Decimal("60") == 0
    assert seconds == Decimal("21120")


def test_a_faster_reach_takes_less_time() -> None:
    upper = travel_seconds(stream(), Decimal("30"), Decimal("22"))
    lower = travel_seconds(stream(), Decimal("22"), Decimal("14"))
    assert lower < upper


def test_water_arrives_after_it_was_let_go() -> None:
    arrival = arrival_of(stream(), Decimal("30"), Decimal("14"), NOON)
    assert arrival > NOON
    assert arrival.date() == NOON.date()


def test_a_long_haul_lands_the_next_day() -> None:
    slow = Stream(
        name="Sanpete Creek",
        reaches=(
            Reach("R1", "Upper", Decimal("60"), Decimal("14"), Decimal("1"), Decimal("0.001")),
        ),
    )
    delivery = release(slow, Decimal("60"), Decimal("14"), Decimal("5"), NOON)
    assert not delivery.arrives_the_same_day


def test_loss_takes_a_bite_out_of_what_arrives() -> None:
    assert carried(stream(), Decimal("30"), Decimal("22"), Decimal("10")) == Decimal("9.200")


def test_a_negative_release_is_refused() -> None:
    with pytest.raises(ValidationError, match="may not be negative"):
        carried(stream(), Decimal("30"), Decimal("22"), Decimal("-1"))


def test_a_release_reports_what_it_cost_to_get_there() -> None:
    delivery = release(stream(), Decimal("30"), Decimal("14"), Decimal("10"), NOON)
    assert delivery.lost_cfs > Decimal("0")
    assert delivery.arriving_cfs + delivery.lost_cfs == delivery.released_cfs
    assert delivery.travel_hours > Decimal("0")


def test_the_release_needed_is_more_than_the_delivery() -> None:
    needed = release_needed_for(stream(), Decimal("30"), Decimal("14"), Decimal("10"))
    assert needed > Decimal("10")
    landed = carried(stream(), Decimal("30"), Decimal("14"), needed)
    assert abs(landed - Decimal("10")) < Decimal("0.01")


def test_a_negative_delivery_is_refused() -> None:
    with pytest.raises(ValidationError, match="may not be negative"):
        release_needed_for(stream(), Decimal("30"), Decimal("14"), Decimal("-1"))


def test_a_reach_that_loses_everything_delivers_nothing() -> None:
    hungry = Stream(
        name="Dry Wash",
        reaches=(
            Reach("R1", "All of it", Decimal("30"), Decimal("10"), Decimal("2"), Decimal("0.05")),
        ),
    )
    with pytest.raises(ValidationError, match="loses everything"):
        release_needed_for(hungry, Decimal("30"), Decimal("10"), Decimal("5"))


def test_water_that_gets_there_in_time_says_so() -> None:
    assert reaches_in_time(stream(), Decimal("30"), Decimal("14"), NOON, datetime(2025, 7, 4, 23))
    assert not reaches_in_time(
        stream(), Decimal("30"), Decimal("14"), NOON, datetime(2025, 7, 4, 12, 30)
    )


def test_water_cannot_be_needed_before_it_was_let_go() -> None:
    with pytest.raises(ValidationError, match="before it was let go"):
        reaches_in_time(stream(), Decimal("30"), Decimal("14"), NOON, datetime(2025, 7, 4, 6))
