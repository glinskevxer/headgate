import sqlite3
from datetime import date, datetime
from decimal import Decimal

import pytest

from headgate.errors import ConflictError
from headgate.ids import DeviceTag, DitchCode, TurnoutCode
from headgate.model.device import Device, DeviceKind
from headgate.model.ditch import Ditch, DitchSystem, Turnout
from headgate.model.reading import ReadingMethod, StaffReading
from headgate.store.repo_devices import save_device
from headgate.store.repo_ditch import save_system
from headgate.store.repo_readings import (
    count_readings,
    delete_reading,
    devices_read_within,
    load_series,
    load_series_within,
    readings_on,
    save_reading,
)
from headgate.wateryear import Span

WEIR = DeviceTag("WEIR-MAIN-3")
METER = DeviceTag("METER-MAIN-3")


def stocked(book: sqlite3.Connection) -> None:
    save_system(
        book,
        DitchSystem(
            ditches=(
                Ditch(
                    code=DitchCode("MAIN"),
                    name="Sanpete Main Canal",
                    capacity_cfs=Decimal("48"),
                    length_feet=Decimal("26400"),
                    loss_fraction_per_mile=Decimal("0.02"),
                    turnouts=(
                        Turnout(
                            TurnoutCode("MAIN-3"),
                            "Bench gate",
                            Decimal("5280"),
                            Decimal("3"),
                            Decimal("40"),
                        ),
                    ),
                    diversion_mile=Decimal("28.4"),
                ),
            )
        ),
    )
    save_device(
        book,
        Device(
            tag=WEIR,
            kind=DeviceKind.CIPOLLETTI_WEIR,
            installed=date(2016, 3, 1),
            crest_width_feet=Decimal("3"),
            turnout=TurnoutCode("MAIN-3"),
        ),
    )
    save_device(
        book,
        Device(
            tag=METER,
            kind=DeviceKind.PROPELLER_METER,
            installed=date(2016, 3, 1),
            turnout=TurnoutCode("MAIN-3"),
        ),
    )


def reading(day: int, head: str = "0.62", hour: int = 7) -> StaffReading:
    return StaffReading(
        device=WEIR,
        taken_at=datetime(2024, 6, day, hour),
        observer="D. Yardley",
        head_feet=Decimal(head),
        note="ran clear",
    )


def test_a_reading_comes_back_the_way_it_went_in(book: sqlite3.Connection) -> None:
    stocked(book)
    save_reading(book, reading(1))
    series = load_series(book, WEIR)
    assert series.readings == (reading(1),)


def test_a_meter_total_survives_the_trip(book: sqlite3.Connection) -> None:
    stocked(book)
    total = StaffReading(
        device=METER,
        taken_at=datetime(2024, 6, 1, 7),
        observer="D. Yardley",
        method=ReadingMethod.METER_TOTAL,
        meter_total_af=Decimal("112.4"),
    )
    save_reading(book, total)
    assert load_series(book, METER).readings[0].meter_total_af == Decimal("112.4")


def test_the_same_device_and_instant_twice_is_a_conflict(book: sqlite3.Connection) -> None:
    stocked(book)
    save_reading(book, reading(1))
    with pytest.raises(ConflictError, match="already read at"):
        save_reading(book, reading(1, "0.70"))


def test_a_reading_for_a_device_that_is_not_there_is_refused(book: sqlite3.Connection) -> None:
    with pytest.raises(sqlite3.IntegrityError):
        save_reading(book, reading(1))


def test_a_series_comes_back_in_time_order(book: sqlite3.Connection) -> None:
    stocked(book)
    for day in (9, 1, 4):
        save_reading(book, reading(day))
    assert [item.taken_at.day for item in load_series(book, WEIR).readings] == [1, 4, 9]


def test_a_span_carries_the_reading_that_opened_it(book: sqlite3.Connection) -> None:
    stocked(book)
    for day in (1, 4, 9):
        save_reading(book, reading(day))
    span = Span(datetime(2024, 6, 5), datetime(2024, 6, 12))
    series = load_series_within(book, WEIR, span)
    assert [item.taken_at.day for item in series.readings] == [4, 9]


def test_a_span_before_any_reading_comes_back_empty(book: sqlite3.Connection) -> None:
    stocked(book)
    save_reading(book, reading(9))
    span = Span(datetime(2024, 5, 1), datetime(2024, 5, 8))
    assert load_series_within(book, WEIR, span).is_empty


def test_everything_read_on_a_day_comes_back(book: sqlite3.Connection) -> None:
    stocked(book)
    save_reading(book, reading(1, hour=7))
    save_reading(book, reading(1, hour=17))
    save_reading(book, reading(2))
    assert len(readings_on(book, date(2024, 6, 1))) == 2


def test_the_devices_read_in_a_span_are_listed(book: sqlite3.Connection) -> None:
    stocked(book)
    save_reading(book, reading(1))
    span = Span(datetime(2024, 6, 1), datetime(2024, 6, 3))
    assert devices_read_within(book, span) == (WEIR,)


def test_readings_are_counted_in_total_and_by_device(book: sqlite3.Connection) -> None:
    stocked(book)
    save_reading(book, reading(1))
    save_reading(book, reading(4))
    assert count_readings(book) == 2
    assert count_readings(book, METER) == 0


def test_a_reading_written_against_the_wrong_device_can_be_struck(
    book: sqlite3.Connection,
) -> None:
    stocked(book)
    save_reading(book, reading(1))
    assert delete_reading(book, WEIR, datetime(2024, 6, 1, 7))
    assert count_readings(book) == 0


def test_striking_a_reading_that_is_not_there_says_so(book: sqlite3.Connection) -> None:
    stocked(book)
    assert not delete_reading(book, WEIR, datetime(2024, 6, 1, 7))
