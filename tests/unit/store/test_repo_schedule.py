import sqlite3
from datetime import date
from decimal import Decimal

import pytest

from headgate.assessment.tiers import Band, RateSchedule
from headgate.errors import ConflictError, NotFoundError
from headgate.money import Money
from headgate.store.repo_schedule import (
    adopt,
    adopted_on,
    adopted_years,
    charge_for,
    load_schedule,
)


def schedule(water_year: int = 2025) -> RateSchedule:
    return RateSchedule(
        water_year=water_year,
        per_share=Money.from_dollars("6.00"),
        bands=(
            Band(Decimal("50"), Money.from_dollars("2.00")),
            Band(Decimal("200"), Money.from_dollars("3.50")),
            Band(None, Money.from_dollars("6.00")),
        ),
        minimum_bill=Money.from_dollars("75.00"),
    )


def test_a_schedule_comes_back_the_way_it_went_in(book: sqlite3.Connection) -> None:
    adopt(book, schedule(), date(2025, 3, 20))
    assert load_schedule(book, 2025) == schedule()


def test_the_bands_keep_their_order(book: sqlite3.Connection) -> None:
    adopt(book, schedule(), date(2025, 3, 20))
    loaded = load_schedule(book, 2025)
    assert loaded.bands[0].upper_af == Decimal("50")
    assert loaded.bands[-1].is_open_ended


def test_the_minimum_survives_the_trip(book: sqlite3.Connection) -> None:
    adopt(book, schedule(), date(2025, 3, 20))
    assert load_schedule(book, 2025).minimum_bill == Money.from_dollars("75.00")


def test_adopting_a_year_twice_is_a_conflict(book: sqlite3.Connection) -> None:
    adopt(book, schedule(), date(2025, 3, 20))
    with pytest.raises(ConflictError, match="already been adopted"):
        adopt(book, schedule(), date(2025, 3, 21))


def test_a_year_with_no_schedule_is_reported_missing(book: sqlite3.Connection) -> None:
    with pytest.raises(NotFoundError, match="no rate schedule"):
        load_schedule(book, 2025)
    with pytest.raises(NotFoundError, match="no rate schedule"):
        adopted_on(book, 2025)


def test_the_day_it_was_adopted_comes_back(book: sqlite3.Connection) -> None:
    adopt(book, schedule(), date(2025, 3, 20))
    assert adopted_on(book, 2025) == date(2025, 3, 20)


def test_the_adopted_years_are_listed(book: sqlite3.Connection) -> None:
    adopt(book, schedule(2024), date(2024, 3, 18))
    adopt(book, schedule(2025), date(2025, 3, 20))
    assert adopted_years(book) == (2024, 2025)


def test_a_charge_can_be_worked_out_straight_off_the_book(book: sqlite3.Connection) -> None:
    adopt(book, schedule(), date(2025, 3, 20))
    assert charge_for(book, 2025, Decimal("20"), Decimal("50")) == Money.from_dollars("220.00")


def test_the_minimum_lifts_a_small_bill(book: sqlite3.Connection) -> None:
    adopt(book, schedule(), date(2025, 3, 20))
    assert charge_for(book, 2025, Decimal("1"), Decimal("0")) == Money.from_dollars("75.00")
