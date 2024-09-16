import sqlite3
from datetime import date, datetime
from decimal import Decimal

import pytest

from headgate.errors import NotFoundError, PolicyError
from headgate.ids import DeviceTag, DitchCode, TurnoutCode
from headgate.measure.quality import Provenance
from headgate.model.device import Calibration, Device, DeviceKind
from headgate.model.ditch import Ditch, DitchSystem, Turnout
from headgate.model.reading import StaffReading
from headgate.store.assemble import (
    build_ledger,
    headgate_volume,
    series_for_turnout,
    turnouts_without_a_device,
)
from headgate.store.repo_devices import save_device
from headgate.store.repo_ditch import save_system
from headgate.store.repo_readings import save_reading
from headgate.wateryear import Span

NEAR = TurnoutCode("MAIN-3")
FAR = TurnoutCode("L2-14")
CALIBRATION = Calibration(date(2024, 4, 1), "R. Aldrich", date(2025, 4, 1))


def system() -> DitchSystem:
    main = Ditch(
        code=DitchCode("MAIN"),
        name="Sanpete Main Canal",
        capacity_cfs=Decimal("48"),
        length_feet=Decimal("26400"),
        loss_fraction_per_mile=Decimal("0.02"),
        turnouts=(Turnout(NEAR, "Bench gate", Decimal("5280"), Decimal("6"), Decimal("40")),),
        diversion_mile=Decimal("28.4"),
    )
    lateral = Ditch(
        code=DitchCode("L2"),
        name="Second Lateral",
        capacity_cfs=Decimal("12"),
        length_feet=Decimal("10560"),
        loss_fraction_per_mile=Decimal("0.05"),
        turnouts=(Turnout(FAR, "Lower gate", Decimal("5280"), Decimal("6"), Decimal("40")),),
        parent=DitchCode("MAIN"),
        offtake_station_feet=Decimal("15840"),
    )
    return DitchSystem(ditches=(main, lateral))


def span() -> Span:
    return Span(datetime(2024, 6, 1, 6), datetime(2024, 6, 11, 6))


def weir(turnout: TurnoutCode) -> Device:
    return Device(
        tag=DeviceTag(f"WEIR-{turnout}"),
        kind=DeviceKind.CIPOLLETTI_WEIR,
        installed=date(2016, 3, 1),
        crest_width_feet=Decimal("3"),
        turnout=turnout,
        calibrations=(CALIBRATION,),
    )


def flume() -> Device:
    return Device(
        tag=DeviceTag("FLUME-MAIN"),
        kind=DeviceKind.PARSHALL_FLUME,
        installed=date(2011, 5, 1),
        throat_width_feet=Decimal("4"),
        ditch=DitchCode("MAIN"),
        calibrations=(CALIBRATION,),
    )


def reading(tag: DeviceTag, head: str, day: int = 1) -> StaffReading:
    return StaffReading(
        device=tag,
        taken_at=datetime(2024, 6, day, 6),
        observer="D. Yardley",
        head_feet=Decimal(head),
    )


def stocked(book: sqlite3.Connection, with_far: bool = True) -> None:
    save_system(book, system())
    save_device(book, weir(NEAR))
    save_reading(book, reading(DeviceTag(f"WEIR-{NEAR}"), "0.60"))
    if with_far:
        save_device(book, weir(FAR))
        save_reading(book, reading(DeviceTag(f"WEIR-{FAR}"), "0.40"))


def test_the_ledger_carries_a_record_for_every_turnout(book: sqlite3.Connection) -> None:
    stocked(book)
    ledger = build_ledger(book, span())
    assert ledger.turnouts == (FAR, NEAR)
    assert ledger.total_af > Decimal("0")


def test_a_turnout_with_no_device_comes_back_void(book: sqlite3.Connection) -> None:
    stocked(book, with_far=False)
    ledger = build_ledger(book, span())
    record = ledger.for_turnout(FAR)
    assert record.provenance is Provenance.VOID
    assert record.total_af == Decimal("0")
    assert ledger.provenance is Provenance.VOID


def test_the_turnouts_with_nothing_measuring_them_are_listed(
    book: sqlite3.Connection,
) -> None:
    stocked(book, with_far=False)
    assert turnouts_without_a_device(book, span()) == (FAR,)


def test_every_turnout_measured_leaves_the_list_empty(book: sqlite3.Connection) -> None:
    stocked(book)
    assert turnouts_without_a_device(book, span()) == ()


def test_the_headgate_volume_comes_off_the_canal_device(book: sqlite3.Connection) -> None:
    stocked(book)
    save_device(book, flume())
    save_reading(book, reading(DeviceTag("FLUME-MAIN"), "1.20"))
    volume = headgate_volume(book, span())
    assert volume.total_af > Decimal("0")
    assert volume.provenance is Provenance.MEASURED


def test_a_canal_with_no_device_cannot_report_a_headgate(book: sqlite3.Connection) -> None:
    stocked(book)
    with pytest.raises(PolicyError, match="no device on it"):
        headgate_volume(book, span())


def test_two_devices_on_the_canal_is_refused(book: sqlite3.Connection) -> None:
    stocked(book)
    save_device(book, flume())
    save_device(
        book,
        Device(
            tag=DeviceTag("FLUME-L2"),
            kind=DeviceKind.CUTTHROAT_FLUME,
            installed=date(2011, 5, 1),
            throat_width_feet=Decimal("2"),
            ditch=DitchCode("MAIN"),
        ),
    )
    with pytest.raises(PolicyError, match="the headgate is one number"):
        headgate_volume(book, span())


def test_a_lateral_can_be_measured_the_same_way(book: sqlite3.Connection) -> None:
    stocked(book)
    save_device(
        book,
        Device(
            tag=DeviceTag("FLUME-L2"),
            kind=DeviceKind.PARSHALL_FLUME,
            installed=date(2011, 5, 1),
            throat_width_feet=Decimal("2"),
            ditch=DitchCode("L2"),
            calibrations=(CALIBRATION,),
        ),
    )
    save_reading(book, reading(DeviceTag("FLUME-L2"), "0.80"))
    volume = headgate_volume(book, span(), DitchCode("L2"))
    assert volume.total_af > Decimal("0")


def test_the_readings_behind_a_turnout_can_be_pulled_out(book: sqlite3.Connection) -> None:
    stocked(book)
    series = series_for_turnout(book, NEAR, span())
    assert len(series.readings) == 1


def test_pulling_readings_for_a_turnout_with_no_device_is_refused(
    book: sqlite3.Connection,
) -> None:
    stocked(book, with_far=False)
    with pytest.raises(NotFoundError):
        series_for_turnout(book, FAR, span())
