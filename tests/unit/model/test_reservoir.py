from datetime import date
from decimal import Decimal

import pytest

from headgate.errors import PolicyError, ValidationError
from headgate.ids import DecreeNumber
from headgate.model.reservoir import PoolState, Reservoir


def reservoir(capacity: str = "4000", dead: str = "300") -> Reservoir:
    return Reservoir(
        name="Ephraim Reservoir",
        decree=DecreeNumber("CDA-1920-40"),
        capacity_af=Decimal(capacity),
        dead_pool_af=Decimal(dead),
    )


def pool(contents: str = "1000", **overrides: object) -> PoolState:
    fields: dict[str, object] = {
        "reservoir": reservoir(),
        "water_year": 2025,
        "contents_af": Decimal(contents),
    }
    fields.update(overrides)
    return PoolState(**fields)  # type: ignore[arg-type]


def test_a_reservoir_holds_something() -> None:
    with pytest.raises(ValidationError, match="holds nothing"):
        reservoir(capacity="0")


def test_a_dead_pool_bigger_than_the_reservoir_is_refused() -> None:
    with pytest.raises(ValidationError, match="dead pool of"):
        reservoir(capacity="400", dead="400")


def test_the_usable_pool_leaves_out_what_is_below_the_outlet() -> None:
    assert reservoir().usable_af == Decimal("3700")


def test_the_fill_season_runs_from_november_to_july() -> None:
    opens, closes = reservoir().fill_window(2025)
    assert opens == date(2024, 11, 1)
    assert closes == date(2025, 7, 1)
    assert reservoir().may_fill_on(date(2025, 4, 1))
    assert not reservoir().may_fill_on(date(2025, 8, 1))


def test_a_pool_cannot_hold_more_than_the_reservoir() -> None:
    with pytest.raises(ValidationError, match="acre foot pool"):
        pool("5000")


def test_a_pool_cannot_hold_a_negative_volume() -> None:
    with pytest.raises(ValidationError, match="negative volume"):
        pool("-1")


def test_the_usable_contents_leave_out_the_dead_pool() -> None:
    assert pool("1000").usable_af == Decimal("700")
    assert pool("200").usable_af == Decimal("0")


def test_a_pool_reports_its_space_and_how_full_it_is() -> None:
    assert pool("1000").space_af == Decimal("3000")
    assert pool("1000").percent_full == Decimal("25.0")
    assert not pool("1000").is_full
    assert pool("4000").is_full


def test_filling_stores_what_fits() -> None:
    filled = pool("1000").fill(Decimal("500"), date(2025, 4, 1))
    assert filled.contents_af == Decimal("1500")
    assert filled.filled_af == Decimal("500")
    assert filled.spilled_af == Decimal("0")


def test_filling_a_full_pool_spills_the_rest() -> None:
    filled = pool("3800").fill(Decimal("500"), date(2025, 4, 1))
    assert filled.contents_af == Decimal("4000")
    assert filled.spilled_af == Decimal("300")


def test_filling_outside_the_fill_season_is_refused() -> None:
    with pytest.raises(PolicyError, match="outside its fill season"):
        pool().fill(Decimal("500"), date(2025, 8, 1))


def test_filling_in_another_water_year_is_refused() -> None:
    with pytest.raises(PolicyError, match="not in water year 2025"):
        pool().fill(Decimal("500"), date(2026, 4, 1))


def test_a_negative_inflow_is_refused() -> None:
    with pytest.raises(ValidationError, match="negative inflow"):
        pool().fill(Decimal("-1"), date(2025, 4, 1))


def test_releasing_water_ends_the_fill_for_the_year() -> None:
    released = pool("2000").release(Decimal("400"))
    assert released.contents_af == Decimal("1600")
    assert released.released_af == Decimal("400")
    assert released.fill_finished


def test_a_second_fill_after_a_release_is_refused() -> None:
    released = pool("2000").release(Decimal("400"))
    with pytest.raises(PolicyError, match="one fill"):
        released.fill(Decimal("100"), date(2025, 5, 1))


def test_nothing_below_the_outlet_can_be_released() -> None:
    with pytest.raises(PolicyError, match="above the outlet"):
        pool("400").release(Decimal("200"))


def test_a_negative_release_is_refused() -> None:
    with pytest.raises(ValidationError, match="negative volume"):
        pool().release(Decimal("-1"))


def test_carryover_rolls_the_pool_into_the_next_year() -> None:
    carried = pool("2000").carry_over(2026)
    assert carried.water_year == 2026
    assert carried.contents_af == Decimal("2000")
    assert carried.filled_af == Decimal("0")
    assert not carried.fill_finished


def test_carryover_over_the_cap_is_spilled() -> None:
    carried = pool("2000").carry_over(2026, Decimal("500"))
    assert carried.usable_af == Decimal("500")
    assert carried.spilled_af == Decimal("1200")


def test_carrying_backwards_is_refused() -> None:
    with pytest.raises(PolicyError, match="does not come after"):
        pool().carry_over(2024)
