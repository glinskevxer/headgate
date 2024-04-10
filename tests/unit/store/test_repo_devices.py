import sqlite3
from datetime import date
from decimal import Decimal

import pytest

from headgate.errors import NotFoundError
from headgate.ids import DeviceTag, DitchCode, TurnoutCode
from headgate.model.device import Calibration, Device, DeviceKind
from headgate.model.ditch import Ditch, DitchSystem, Turnout
from headgate.store.repo_devices import (
    device_at_turnout,
    load_device,
    load_devices,
    save_device,
    uncalibrated_on,
)
from headgate.store.repo_ditch import save_system

CALIBRATION = Calibration(date(2024, 4, 1), "R. Aldrich", date(2025, 4, 1), Decimal("0.02"))


def system() -> DitchSystem:
    return DitchSystem(
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
    )


def weir(**overrides: object) -> Device:
    fields: dict[str, object] = {
        "tag": DeviceTag("WEIR-MAIN-3"),
        "kind": DeviceKind.CIPOLLETTI_WEIR,
        "installed": date(2016, 3, 1),
        "crest_width_feet": Decimal("3"),
        "turnout": TurnoutCode("MAIN-3"),
        "calibrations": (CALIBRATION,),
    }
    fields.update(overrides)
    return Device(**fields)  # type: ignore[arg-type]


def stocked(book: sqlite3.Connection) -> None:
    save_system(book, system())


def test_a_device_comes_back_with_its_calibrations(book: sqlite3.Connection) -> None:
    stocked(book)
    save_device(book, weir())
    loaded = load_device(book, DeviceTag("WEIR-MAIN-3"))
    assert loaded == weir()
    assert loaded.staff_offset_on(date(2024, 6, 1)) == Decimal("0.02")


def test_saving_a_device_again_adds_the_new_calibration(book: sqlite3.Connection) -> None:
    stocked(book)
    save_device(book, weir())
    later = Calibration(date(2025, 4, 2), "R. Aldrich", date(2026, 4, 2))
    save_device(book, weir().with_calibration(later))
    loaded = load_device(book, DeviceTag("WEIR-MAIN-3"))
    assert len(loaded.calibrations) == 2
    assert loaded.is_calibrated_on(date(2025, 6, 1))


def test_a_flume_keeps_its_throat_width(book: sqlite3.Connection) -> None:
    stocked(book)
    flume = Device(
        tag=DeviceTag("FLUME-MAIN"),
        kind=DeviceKind.PARSHALL_FLUME,
        installed=date(2011, 5, 1),
        throat_width_feet=Decimal("4"),
        ditch=DitchCode("MAIN"),
    )
    save_device(book, flume)
    assert load_device(book, DeviceTag("FLUME-MAIN")).throat_width_feet == Decimal("4")


def test_a_device_that_is_not_there_is_reported_missing(book: sqlite3.Connection) -> None:
    with pytest.raises(NotFoundError, match="no device"):
        load_device(book, DeviceTag("WEIR-L2-14"))


def test_devices_come_back_in_tag_order(book: sqlite3.Connection) -> None:
    stocked(book)
    save_device(book, weir())
    save_device(
        book,
        Device(
            tag=DeviceTag("FLUME-MAIN"),
            kind=DeviceKind.CUTTHROAT_FLUME,
            installed=date(2011, 5, 1),
            throat_width_feet=Decimal("2"),
            ditch=DitchCode("MAIN"),
        ),
    )
    assert [str(item.tag) for item in load_devices(book)] == ["FLUME-MAIN", "WEIR-MAIN-3"]


def test_the_device_in_a_turnout_is_the_one_in_service(book: sqlite3.Connection) -> None:
    stocked(book)
    save_device(book, weir(removed=date(2020, 1, 1)))
    save_device(
        book,
        weir(
            tag=DeviceTag("WEIR-MAIN-3"),
            installed=date(2020, 1, 1),
            crest_width_feet=Decimal("4"),
        ),
    )
    found = device_at_turnout(book, TurnoutCode("MAIN-3"), date(2024, 6, 1))
    assert found.crest_width_feet == Decimal("4")


def test_a_turnout_with_nothing_in_it_reports_missing(book: sqlite3.Connection) -> None:
    stocked(book)
    with pytest.raises(NotFoundError, match="no device in service"):
        device_at_turnout(book, TurnoutCode("MAIN-3"), date(2024, 6, 1))


def test_a_device_out_of_the_ditch_is_not_the_one_in_service(book: sqlite3.Connection) -> None:
    stocked(book)
    save_device(book, weir(removed=date(2020, 1, 1)))
    with pytest.raises(NotFoundError):
        device_at_turnout(book, TurnoutCode("MAIN-3"), date(2024, 6, 1))


def test_devices_with_a_lapsed_calibration_are_listed(book: sqlite3.Connection) -> None:
    stocked(book)
    save_device(book, weir())
    assert uncalibrated_on(book, date(2024, 6, 1)) == ()
    lapsed = uncalibrated_on(book, date(2025, 6, 1))
    assert [str(item.tag) for item in lapsed] == ["WEIR-MAIN-3"]


def test_a_device_needs_a_turnout_or_a_ditch_and_not_both(book: sqlite3.Connection) -> None:
    stocked(book)
    with pytest.raises(sqlite3.IntegrityError):
        book.execute(
            "INSERT INTO device (tag, kind, installed, min_head_feet, max_head_feet)"
            " VALUES ('WEIR-MAIN-9', 'cipolletti_weir', '2016-03-01', '0.05', '2.0')"
        )
