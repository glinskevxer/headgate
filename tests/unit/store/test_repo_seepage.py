import sqlite3
from datetime import date
from decimal import Decimal

import pytest

from headgate.errors import ConflictError, PolicyError
from headgate.ids import DitchCode
from headgate.model.seepage import SeepageRun
from headgate.store.repo_ditch import load_system, save_system
from headgate.store.repo_seepage import (
    adopt_measured_rate,
    ditches_run,
    load_history,
    record_run,
)
from tests.support.district import lateral

L2 = DitchCode("L2")


def stocked(book: sqlite3.Connection) -> None:
    save_system(book, lateral())


def run(
    inflow: str = "10",
    outflow: str = "9",
    on: date = date(2025, 5, 20),
    turnouts: str = "0",
) -> SeepageRun:
    return SeepageRun(
        ditch=L2,
        run_on=on,
        from_station_feet=Decimal("0"),
        to_station_feet=Decimal("5280"),
        inflow_cfs=Decimal(inflow),
        outflow_cfs=Decimal(outflow),
        turnouts_running_cfs=Decimal(turnouts),
        note="turnouts shut, two flumes",
    )


def test_a_run_comes_back_the_way_it_went_in(book: sqlite3.Connection) -> None:
    stocked(book)
    record_run(book, run())
    history = load_history(book, L2)
    assert history.runs == (run(),)
    assert history.latest().note == "turnouts shut, two flumes"


def test_the_same_reach_on_the_same_day_twice_is_a_conflict(
    book: sqlite3.Connection,
) -> None:
    stocked(book)
    record_run(book, run())
    with pytest.raises(ConflictError, match="already run from station"):
        record_run(book, run())


def test_a_run_on_a_ditch_that_is_not_there_is_refused(book: sqlite3.Connection) -> None:
    with pytest.raises(sqlite3.IntegrityError):
        record_run(book, run())


def test_the_runs_come_back_oldest_first(book: sqlite3.Connection) -> None:
    stocked(book)
    record_run(book, run(on=date(2025, 7, 1)))
    record_run(book, run(on=date(2025, 5, 1)))
    assert [item.run_on.month for item in load_history(book, L2).runs] == [5, 7]


def test_adopting_the_measured_rate_changes_the_ditch(book: sqlite3.Connection) -> None:
    stocked(book)
    assert load_system(book).ditch(L2).loss_fraction_per_mile == Decimal("0.05")
    record_run(book, run())
    measured = adopt_measured_rate(book, L2)
    assert measured == Decimal("0.1000")
    assert load_system(book).ditch(L2).loss_fraction_per_mile == Decimal("0.1000")


def test_a_ditch_with_no_usable_run_adopts_nothing(book: sqlite3.Connection) -> None:
    stocked(book)
    record_run(book, run(outflow="9.95"))
    with pytest.raises(PolicyError, match="worth setting a loss rate"):
        adopt_measured_rate(book, L2)


def test_a_gaining_ditch_cannot_adopt_a_loss_rate(book: sqlite3.Connection) -> None:
    stocked(book)
    record_run(book, run(outflow="11"))
    with pytest.raises(PolicyError, match="worth setting a loss rate"):
        adopt_measured_rate(book, L2)


def test_two_runs_average_before_they_are_adopted(book: sqlite3.Connection) -> None:
    stocked(book)
    record_run(book, run(on=date(2025, 5, 1)))
    record_run(book, run(outflow="8.8", on=date(2025, 6, 1)))
    measured = adopt_measured_rate(book, L2)
    assert Decimal("0.1") < measured < Decimal("0.12")


def test_the_ditches_that_have_been_run_are_listed(book: sqlite3.Connection) -> None:
    stocked(book)
    assert ditches_run(book) == ()
    record_run(book, run())
    assert ditches_run(book) == (L2,)


def test_a_ditch_nobody_has_run_has_an_empty_history(book: sqlite3.Connection) -> None:
    stocked(book)
    assert load_history(book, L2).runs == ()
