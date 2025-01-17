from datetime import date, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest

from headgate.ids import AccountNumber, DeviceTag, DitchCode, TurnoutCode
from headgate.model.account import Account, AccountStatus, ShareCertificate, ShareRegister
from headgate.model.device import Calibration, Device, DeviceKind
from headgate.model.ditch import Ditch, DitchSystem, Turnout
from headgate.model.reading import StaffReading
from headgate.store.db import Database
from headgate.store.repo_accounts import save_register
from headgate.store.repo_devices import save_device
from headgate.store.repo_ditch import save_system
from headgate.store.repo_readings import save_reading
from headgate.store.repo_season import declare_season
from headgate.wateryear import IrrigationSeason
from tests.support.district import init_book, run

BENCH = TurnoutCode("MAIN-3")
LOWER = TurnoutCode("L2-14")
PETERSON = AccountNumber(118)
LARSEN = AccountNumber(212)
CALIBRATION = Calibration(date(2025, 4, 1), "R. Aldrich", date(2026, 4, 1))


def system() -> DitchSystem:
    main = Ditch(
        code=DitchCode("MAIN"),
        name="Sanpete Main Canal",
        capacity_cfs=Decimal("48"),
        length_feet=Decimal("26400"),
        loss_fraction_per_mile=Decimal("0.02"),
        turnouts=(Turnout(BENCH, "Bench gate", Decimal("5280"), Decimal("8"), Decimal("60")),),
        diversion_mile=Decimal("28.4"),
    )
    lateral = Ditch(
        code=DitchCode("L2"),
        name="Second Lateral",
        capacity_cfs=Decimal("12"),
        length_feet=Decimal("10560"),
        loss_fraction_per_mile=Decimal("0.05"),
        turnouts=(Turnout(LOWER, "Lower gate", Decimal("5280"), Decimal("6"), Decimal("40")),),
        parent=DitchCode("MAIN"),
        offtake_station_feet=Decimal("15840"),
    )
    return DitchSystem(ditches=(main, lateral))


def weir(turnout: TurnoutCode, crest: str) -> Device:
    return Device(
        tag=DeviceTag(f"WEIR-{turnout}"),
        kind=DeviceKind.CIPOLLETTI_WEIR,
        installed=date(2016, 3, 1),
        crest_width_feet=Decimal(crest),
        turnout=turnout,
        calibrations=(CALIBRATION,),
    )


def flume() -> Device:
    return Device(
        tag=DeviceTag("FLUME-MAIN"),
        kind=DeviceKind.PARSHALL_FLUME,
        installed=date(2011, 5, 1),
        throat_width_feet=Decimal("6"),
        ditch=DitchCode("MAIN"),
        calibrations=(CALIBRATION,),
    )


def readings(connection: object, tag: str, head: str) -> None:
    start = datetime(2025, 4, 15, 6)
    for index in range(16):
        save_reading(
            connection,  # type: ignore[arg-type]
            StaffReading(
                device=DeviceTag(tag),
                taken_at=start + timedelta(days=index * 10),
                observer="D. Yardley",
                head_feet=Decimal(head),
            ),
        )


@pytest.fixture
def district(tmp_path: Path) -> Path:
    book = init_book(tmp_path / "district.sqlite3")
    with Database(book).open() as connection:
        save_system(connection, system())
        save_register(
            connection,
            ShareRegister(
                accounts=(
                    Account(PETERSON, "Alma Peterson", date(1994, 3, 1), AccountStatus.ACTIVE),
                    Account(LARSEN, "Ruth Larsen", date(1998, 5, 1), AccountStatus.ACTIVE),
                ),
                certificates=(
                    ShareCertificate("A-1001", PETERSON, Decimal("24"), BENCH, date(2005, 4, 1)),
                    ShareCertificate("A-1002", LARSEN, Decimal("16"), LOWER, date(2005, 4, 1)),
                ),
            ),
        )
        declare_season(connection, IrrigationSeason.default_for(2025), date(2025, 3, 20))
        save_device(connection, weir(BENCH, "4"))
        save_device(connection, weir(LOWER, "3"))
        save_device(connection, flume())
        readings(connection, f"WEIR-{BENCH}", "0.80")
        readings(connection, f"WEIR-{LOWER}", "0.55")
        readings(connection, "FLUME-MAIN", "1.50")
    run(
        book,
        [
            "season",
            "rates",
            "--year",
            "2025",
            "--per-share",
            "6.00",
            "--band",
            "50:2.00",
            "--band",
            "200:3.50",
            "--band",
            "open:6.00",
            "--adopted",
            "2025-03-20",
        ],
    )
    return book


def test_a_dry_run_prints_the_numbers_and_writes_nothing(district: Path) -> None:
    code, output = run(
        district, ["season", "close", "--year", "2025", "--issued", "2025-11-01", "--dry-run"]
    )
    assert code == 0
    assert "delivered" in output
    assert "this was a dry run" in output
    code, output = run(
        district, ["season", "close", "--year", "2025", "--issued", "2025-11-01", "--dry-run"]
    )
    assert code == 0


def test_closing_writes_the_bills_and_posts_the_journal(district: Path) -> None:
    code, output = run(district, ["season", "close", "--year", "2025", "--issued", "2025-11-01"])
    assert code == 0
    assert "2 bills written" in output
    assert "billed" in output


def test_a_season_is_only_closed_once(district: Path) -> None:
    run(district, ["season", "close", "--year", "2025", "--issued", "2025-11-01"])
    code, output = run(district, ["season", "close", "--year", "2025", "--issued", "2025-11-01"])
    assert code != 0
    assert "already been billed" in output


def test_a_year_with_no_rates_cannot_be_closed(district: Path) -> None:
    code, output = run(district, ["season", "close", "--year", "2024", "--issued", "2024-11-01"])
    assert code != 0
    assert "no season" in output or "no rate schedule" in output


def test_the_loss_rule_can_be_chosen(district: Path) -> None:
    code, output = run(
        district,
        ["season", "close", "--year", "2025", "--issued", "2025-11-01", "--loss", "by-share"],
    )
    assert code == 0
    assert "ditch loss" in output


def test_a_turnout_with_two_shareholders_stops_the_close(district: Path) -> None:
    with Database(district).open() as connection:
        save_register(
            connection,
            ShareRegister(
                accounts=(
                    Account(PETERSON, "Alma Peterson", date(1994, 3, 1), AccountStatus.ACTIVE),
                    Account(LARSEN, "Ruth Larsen", date(1998, 5, 1), AccountStatus.ACTIVE),
                ),
                certificates=(
                    ShareCertificate("A-1001", PETERSON, Decimal("24"), BENCH, date(2005, 4, 1)),
                    ShareCertificate("A-1002", LARSEN, Decimal("16"), LOWER, date(2005, 4, 1)),
                    ShareCertificate("A-1003", PETERSON, Decimal("4"), LOWER, date(2011, 4, 1)),
                ),
            ),
        )
    code, output = run(district, ["season", "close", "--year", "2025", "--issued", "2025-11-01"])
    assert code != 0
    assert "does not say" in output
