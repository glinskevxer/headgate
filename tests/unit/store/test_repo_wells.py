import sqlite3
from datetime import date
from decimal import Decimal

import pytest

from headgate.errors import NotFoundError
from headgate.ids import DecreeNumber
from headgate.model.right import Priority, RightKind, WaterRight
from headgate.store.repo_rights import save_right
from headgate.store.repo_wells import (
    load_well,
    load_wells,
    pumped_total,
    pumping_for,
    pumping_in,
    record_pumping,
    save_well,
)
from headgate.wells.depletion import Well

DECREE = DecreeNumber("CDA-1972-14")


def stocked(book: sqlite3.Connection) -> None:
    save_right(
        book,
        WaterRight(
            decree=DECREE,
            owner="Alma Peterson",
            kind=RightKind.DIRECT_FLOW,
            priority=Priority(date(1968, 5, 1), 1972, 14),
            diversion_mile=Decimal("21"),
            rate_cfs=Decimal("2"),
        ),
    )


def well(well_id: str = "W-14", distance: str = "1500", limit: str | None = "200") -> Well:
    return Well(
        well_id=well_id,
        decree=DECREE,
        distance_to_stream_feet=Decimal(distance),
        storativity=Decimal("0.15"),
        transmissivity_ft2_day=Decimal("15000"),
        capacity_gpm=Decimal("900"),
        annual_limit_af=Decimal(limit) if limit is not None else None,
    )


def test_a_well_comes_back_the_way_it_went_in(book: sqlite3.Connection) -> None:
    stocked(book)
    save_well(book, well())
    assert load_well(book, "W-14") == well()


def test_a_well_with_no_limit_survives_the_trip(book: sqlite3.Connection) -> None:
    stocked(book)
    save_well(book, well(limit=None))
    assert load_well(book, "W-14").annual_limit_af is None


def test_a_well_against_a_decree_that_is_not_there_is_refused(
    book: sqlite3.Connection,
) -> None:
    with pytest.raises(sqlite3.IntegrityError):
        save_well(book, well())


def test_a_well_that_is_not_there_is_reported_missing(book: sqlite3.Connection) -> None:
    with pytest.raises(NotFoundError, match="no well"):
        load_well(book, "W-99")


def test_wells_come_back_in_order(book: sqlite3.Connection) -> None:
    stocked(book)
    save_well(book, well("W-20"))
    save_well(book, well("W-14"))
    assert [item.well_id for item in load_wells(book)] == ["W-14", "W-20"]


def test_pumping_is_recorded_by_the_month(book: sqlite3.Connection) -> None:
    stocked(book)
    save_well(book, well())
    record_pumping(book, "W-14", 2025, 6, Decimal("40"))
    record_pumping(book, "W-14", 2025, 7, Decimal("60"))
    records = pumping_for(book, "W-14", 2025)
    assert [item.month for item in records] == [6, 7]
    assert pumped_total(book, "W-14", 2025) == Decimal("100.0000")


def test_a_month_read_wrong_is_written_over(book: sqlite3.Connection) -> None:
    stocked(book)
    save_well(book, well())
    record_pumping(book, "W-14", 2025, 6, Decimal("40"))
    record_pumping(book, "W-14", 2025, 6, Decimal("35"))
    assert pumped_total(book, "W-14", 2025) == Decimal("35.0000")


def test_pumping_for_a_well_that_is_not_there_is_refused(book: sqlite3.Connection) -> None:
    with pytest.raises(NotFoundError, match="no well"):
        record_pumping(book, "W-99", 2025, 6, Decimal("40"))


def test_a_month_outside_the_year_is_refused(book: sqlite3.Connection) -> None:
    stocked(book)
    save_well(book, well())
    with pytest.raises(sqlite3.IntegrityError):
        book.execute(
            "INSERT INTO well_pumping (well_id, water_year, month, pumped_af)"
            " VALUES ('W-14', 2025, 13, '10')"
        )


def test_every_wells_pumping_comes_back_for_a_year(book: sqlite3.Connection) -> None:
    stocked(book)
    save_well(book, well("W-14"))
    save_well(book, well("W-20"))
    record_pumping(book, "W-14", 2025, 6, Decimal("40"))
    record_pumping(book, "W-20", 2025, 7, Decimal("20"))
    record_pumping(book, "W-20", 2024, 7, Decimal("30"))
    records = pumping_in(book, 2025)
    assert len(records) == 2
    assert {item.well.well_id for item in records} == {"W-14", "W-20"}


def test_a_year_with_no_pumping_totals_nothing(book: sqlite3.Connection) -> None:
    stocked(book)
    save_well(book, well())
    assert pumped_total(book, "W-14", 2025) == Decimal("0")
    assert pumping_for(book, "W-14", 2025) == ()
