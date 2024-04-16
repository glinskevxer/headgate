import sqlite3
from datetime import date

import pytest

from headgate.errors import ConflictError, NotFoundError, PolicyError
from headgate.store.repo_season import (
    close_early,
    declaration_note,
    declare_season,
    list_seasons,
    load_season,
    season_for,
)
from headgate.wateryear import IrrigationSeason


def season(year: int = 2025) -> IrrigationSeason:
    return IrrigationSeason.default_for(year)


def test_a_declared_season_comes_back(book: sqlite3.Connection) -> None:
    declare_season(book, season(), date(2025, 3, 20), "board voted 5 to 0")
    assert load_season(book, 2025) == season()
    assert declaration_note(book, 2025) == "board voted 5 to 0"


def test_a_season_declared_after_it_opened_is_refused(book: sqlite3.Connection) -> None:
    with pytest.raises(PolicyError, match="already running"):
        declare_season(book, season(), date(2025, 5, 1))


def test_declaring_the_same_year_twice_is_a_conflict(book: sqlite3.Connection) -> None:
    declare_season(book, season(), date(2025, 3, 20))
    with pytest.raises(ConflictError, match="already been declared"):
        declare_season(book, season(), date(2025, 3, 21))


def test_a_year_that_was_never_declared_is_reported_missing(book: sqlite3.Connection) -> None:
    with pytest.raises(NotFoundError, match="no season"):
        load_season(book, 2025)


def test_a_day_finds_the_season_it_falls_in(book: sqlite3.Connection) -> None:
    declare_season(book, season(), date(2025, 3, 20))
    assert season_for(book, date(2025, 7, 4)).water_year == 2025


def test_a_day_outside_the_declared_season_is_refused(book: sqlite3.Connection) -> None:
    declare_season(book, season(), date(2025, 3, 20))
    with pytest.raises(PolicyError, match="outside the declared season"):
        season_for(book, date(2025, 3, 1))


def test_seasons_come_back_in_year_order(book: sqlite3.Connection) -> None:
    declare_season(book, season(2025), date(2025, 3, 20))
    declare_season(book, season(2024), date(2024, 3, 18))
    assert [item.water_year for item in list_seasons(book)] == [2024, 2025]


def test_a_short_year_closes_early(book: sqlite3.Connection) -> None:
    declare_season(book, season(), date(2025, 3, 20))
    shortened = close_early(book, 2025, date(2025, 8, 15), "creek quit")
    assert shortened.closed == date(2025, 8, 15)
    assert load_season(book, 2025).closed == date(2025, 8, 15)
    assert declaration_note(book, 2025) == "creek quit"


def test_closing_later_than_declared_is_not_closing_early(book: sqlite3.Connection) -> None:
    declare_season(book, season(), date(2025, 3, 20))
    with pytest.raises(PolicyError, match="not earlier than"):
        close_early(book, 2025, date(2025, 10, 20), "wet year")


def test_closing_a_year_that_was_never_declared_is_refused(book: sqlite3.Connection) -> None:
    with pytest.raises(NotFoundError):
        close_early(book, 2025, date(2025, 8, 15), "creek quit")


def test_a_note_for_a_year_that_is_not_there_is_refused(book: sqlite3.Connection) -> None:
    with pytest.raises(NotFoundError):
        declaration_note(book, 2025)
