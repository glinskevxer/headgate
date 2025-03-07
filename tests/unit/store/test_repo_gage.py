import sqlite3
from datetime import date, timedelta
from decimal import Decimal

import pytest

from headgate.errors import NotFoundError
from headgate.model.gage import DailyMean, RecordGrade
from headgate.model.stream import GagePoint
from headgate.store.repo_gage import (
    count_days,
    flow_on,
    gages,
    load_gage,
    load_hydrograph,
    record_day,
    save_gage,
)

FIRST = date(2025, 6, 1)


def gage(code: str = "SANP-1", mile: str = "22") -> GagePoint:
    return GagePoint(
        code=code,
        name="Below the forks",
        mile=Decimal(mile),
        datum_elevation_feet=Decimal("5412.30"),
    )


def reading(offset: int, cfs: str, grade: RecordGrade = RecordGrade.MEASURED) -> DailyMean:
    return DailyMean(day=FIRST + timedelta(days=offset), mean_cfs=Decimal(cfs), grade=grade)


def test_a_gage_comes_back_the_way_it_went_in(book: sqlite3.Connection) -> None:
    save_gage(book, gage())
    assert load_gage(book, "SANP-1") == gage()


def test_a_gage_that_is_not_there_is_reported_missing(book: sqlite3.Connection) -> None:
    with pytest.raises(NotFoundError, match="no gage"):
        load_gage(book, "SANP-9")


def test_gages_come_back_from_the_top_of_the_creek_down(book: sqlite3.Connection) -> None:
    save_gage(book, gage("SANP-2", "14"))
    save_gage(book, gage("SANP-1", "22"))
    assert [item.code for item in gages(book)] == ["SANP-1", "SANP-2"]


def test_a_day_is_written_and_read_back(book: sqlite3.Connection) -> None:
    save_gage(book, gage())
    record_day(book, "SANP-1", reading(0, "18.4"))
    record = load_hydrograph(book, "SANP-1")
    assert record.on(FIRST).mean_cfs == Decimal("18.4")
    assert count_days(book, "SANP-1") == 1


def test_a_corrected_day_is_written_over(book: sqlite3.Connection) -> None:
    save_gage(book, gage())
    record_day(book, "SANP-1", reading(0, "18.4"))
    record_day(book, "SANP-1", reading(0, "16.9", RecordGrade.ESTIMATED))
    record = load_hydrograph(book, "SANP-1")
    assert record.on(FIRST).mean_cfs == Decimal("16.9")
    assert record.on(FIRST).grade is RecordGrade.ESTIMATED
    assert count_days(book, "SANP-1") == 1


def test_a_day_for_a_gage_that_is_not_there_is_refused(book: sqlite3.Connection) -> None:
    with pytest.raises(sqlite3.IntegrityError):
        record_day(book, "SANP-9", reading(0, "18.4"))


def test_a_span_pulls_only_the_days_inside_it(book: sqlite3.Connection) -> None:
    save_gage(book, gage())
    for offset in range(10):
        record_day(book, "SANP-1", reading(offset, str(20 - offset)))
    record = load_hydrograph(book, "SANP-1", FIRST, FIRST + timedelta(days=4))
    assert len(record.days) == 4
    assert record.coverage(FIRST, FIRST + timedelta(days=4)) == Decimal("1.000")


def test_the_flow_on_a_day_comes_back_on_its_own(book: sqlite3.Connection) -> None:
    save_gage(book, gage())
    record_day(book, "SANP-1", reading(0, "18.4"))
    assert flow_on(book, "SANP-1", FIRST) == Decimal("18.4")
    with pytest.raises(NotFoundError, match="no gage record"):
        flow_on(book, "SANP-1", FIRST + timedelta(days=1))


def test_a_gage_nobody_has_read_has_an_empty_record(book: sqlite3.Connection) -> None:
    save_gage(book, gage())
    assert load_hydrograph(book, "SANP-1").days == ()
    assert count_days(book, "SANP-1") == 0


def test_the_ice_affected_days_survive_the_trip(book: sqlite3.Connection) -> None:
    save_gage(book, gage())
    record_day(book, "SANP-1", reading(0, "4.2", RecordGrade.ICE_AFFECTED))
    record = load_hydrograph(book, "SANP-1")
    assert record.graded(RecordGrade.ICE_AFFECTED)
    assert not record.is_proved(FIRST, FIRST + timedelta(days=1))
