import sqlite3
from datetime import datetime
from decimal import Decimal

import pytest

from headgate.errors import PolicyError
from headgate.ids import DitchCode, TurnoutCode
from headgate.model.ditch import Ditch, DitchSystem, Turnout
from headgate.rotation.plan import RotationPlan, RunWindow
from headgate.store.repo_ditch import save_system
from headgate.store.repo_rotation import (
    count_windows,
    hours_for,
    load_plan,
    next_window,
    running_at,
    save_plan,
    years_planned,
)
from headgate.wateryear import Span

FIRST = TurnoutCode("L2-14")
SECOND = TurnoutCode("L2-20")


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
                        Turnout(FIRST, "Lower gate", Decimal("5280"), Decimal("6"), Decimal("40")),
                        Turnout(SECOND, "Tail gate", Decimal("9000"), Decimal("4"), Decimal("25")),
                    ),
                    diversion_mile=Decimal("28.4"),
                ),
            )
        ),
    )


def window(turnout: TurnoutCode, first_day: int, last_day: int, rate: str) -> RunWindow:
    return RunWindow(
        turnout=turnout,
        span=Span(datetime(2025, 7, first_day, 6), datetime(2025, 7, last_day, 6)),
        rate_cfs=Decimal(rate),
    )


def plan() -> RotationPlan:
    return RotationPlan(
        water_year=2025,
        windows=(window(FIRST, 1, 3, "6"), window(SECOND, 3, 5, "4"), window(FIRST, 5, 7, "6")),
    )


def test_a_plan_comes_back_the_way_it_went_in(book: sqlite3.Connection) -> None:
    stocked(book)
    save_plan(book, plan())
    assert load_plan(book, 2025) == plan()


def test_saving_again_replaces_the_year(book: sqlite3.Connection) -> None:
    stocked(book)
    save_plan(book, plan())
    save_plan(book, RotationPlan(water_year=2025, windows=(window(FIRST, 1, 2, "6"),)))
    assert count_windows(book, 2025) == 1


def test_a_window_for_a_turnout_that_is_not_there_is_refused(
    book: sqlite3.Connection,
) -> None:
    with pytest.raises(sqlite3.IntegrityError):
        save_plan(book, plan())


def test_the_windows_open_at_a_moment_come_back(book: sqlite3.Connection) -> None:
    stocked(book)
    save_plan(book, plan())
    running = running_at(book, datetime(2025, 7, 2, 12))
    assert [item.turnout for item in running] == [FIRST]


def test_nothing_is_running_between_the_cycles(book: sqlite3.Connection) -> None:
    stocked(book)
    save_plan(book, plan())
    assert running_at(book, datetime(2025, 8, 2, 12)) == ()


def test_the_next_turn_for_a_turnout_is_found(book: sqlite3.Connection) -> None:
    stocked(book)
    save_plan(book, plan())
    found = next_window(book, FIRST, datetime(2025, 7, 2, 12))
    assert found.span.start == datetime(2025, 7, 5, 6)


def test_a_turnout_that_does_not_come_round_again_says_so(book: sqlite3.Connection) -> None:
    stocked(book)
    save_plan(book, plan())
    with pytest.raises(PolicyError, match="does not come round again"):
        next_window(book, SECOND, datetime(2025, 7, 6, 12))


def test_the_hours_a_turnout_gets_add_up(book: sqlite3.Connection) -> None:
    stocked(book)
    save_plan(book, plan())
    assert hours_for(book, FIRST, 2025) == Decimal("96.00")
    assert hours_for(book, SECOND, 2025) == Decimal("48.00")


def test_the_years_with_a_rotation_are_listed(book: sqlite3.Connection) -> None:
    stocked(book)
    save_plan(book, plan())
    save_plan(book, RotationPlan(water_year=2024, windows=()))
    assert years_planned(book) == (2025,)


def test_a_year_with_no_rotation_reads_empty(book: sqlite3.Connection) -> None:
    assert load_plan(book, 2025).windows == ()
    assert count_windows(book, 2025) == 0
