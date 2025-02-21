from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

import pytest
from click.testing import CliRunner

from headgate.cli.main import main
from headgate.cli.reports import check_policy
from headgate.errors import PolicyError
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

NEAR = TurnoutCode("MAIN-3")
FAR = TurnoutCode("L2-14")
CALIBRATION = Calibration(date(2025, 4, 1), "R. Aldrich", date(2026, 4, 1))


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


def reading(tag: DeviceTag, head: str, day: int = 15) -> StaffReading:
    return StaffReading(
        device=tag,
        taken_at=datetime(2025, 4, day, 6),
        observer="D. Yardley",
        head_feet=Decimal(head),
    )


@pytest.fixture
def district(tmp_path: Path) -> Path:
    book = tmp_path / "district.sqlite3"
    CliRunner().invoke(
        main,
        [
            "--book",
            str(book),
            "init",
            "--name",
            "Sanpete Ditch Company",
            "--state",
            "ut",
            "--stream",
            "Sanpete Creek",
        ],
    )
    with Database(book).open() as connection:
        save_system(connection, system())
        save_register(
            connection,
            ShareRegister(
                accounts=(
                    Account(
                        AccountNumber(118), "Holder 118", date(1994, 3, 1), AccountStatus.ACTIVE
                    ),
                ),
                certificates=(
                    ShareCertificate(
                        "A-1001", AccountNumber(118), Decimal("20"), FAR, date(2020, 4, 1)
                    ),
                ),
            ),
        )
        declare_season(connection, IrrigationSeason.default_for(2025), date(2025, 3, 20))
        save_device(connection, weir(NEAR))
        save_device(connection, weir(FAR))
        save_device(connection, flume())
        save_reading(connection, reading(DeviceTag(f"WEIR-{NEAR}"), "0.60"))
        save_reading(connection, reading(DeviceTag(f"WEIR-{FAR}"), "0.40"))
        save_reading(connection, reading(DeviceTag("FLUME-MAIN"), "1.60"))
    return book


def run(book: Path, arguments: list[str]) -> tuple[int, str]:
    result = CliRunner().invoke(main, ["--book", str(book), *arguments])
    return result.exit_code, result.output


def test_the_season_report_prints_the_summary_and_the_turnouts(district: Path) -> None:
    code, output = run(district, ["report", "season", "2025"])
    assert code == 0
    assert "Sanpete Ditch Company" in output
    assert "MAIN-3" in output
    assert "L2-14" in output
    assert "carriage" in output


def test_the_loss_rule_can_be_chosen(district: Path) -> None:
    code, output = run(district, ["report", "season", "2025", "--loss", "by-delivery"])
    assert code == 0
    assert "ditch loss" in output


def test_an_unknown_loss_rule_is_refused(district: Path) -> None:
    code, output = run(district, ["report", "season", "2025", "--loss", "by-guess"])
    assert code != 0
    assert "by-guess" in output


def test_a_year_that_was_never_declared_is_refused(district: Path) -> None:
    code, output = run(district, ["report", "season", "2024"])
    assert code != 0
    assert "no season" in output


def test_the_turnout_report_shows_the_segments(district: Path) -> None:
    code, output = run(
        district,
        ["report", "turnout", "L2-14", "--from", "2025-04-15T06:00", "--to", "2025-04-25T06:00"],
    )
    assert code == 0
    assert "WEIR-L2-14" in output
    assert "measured" in output


def test_the_gaps_report_finds_a_clean_season(district: Path) -> None:
    code, output = run(district, ["report", "gaps", "2025"])
    assert code == 0
    assert "hours unaccounted for" in output or "every turnout was measured" in output


def test_nothing_running_says_so(district: Path) -> None:
    code, output = run(district, ["report", "running", "--at", "2025-07-04T12:00"])
    assert code == 0
    assert "nothing was running" in output


def test_a_running_order_shows_up(district: Path) -> None:
    run(
        district,
        [
            "order",
            "place",
            "--account",
            "118",
            "--turnout",
            "L2-14",
            "--rate",
            "3",
            "--from",
            "2025-07-01T06:00",
            "--to",
            "2025-07-08T06:00",
            "--placed",
            "2025-06-28T08:00",
        ],
    )
    run(district, ["order", "answer", "1"])
    code, output = run(district, ["report", "running", "--at", "2025-07-04T12:00"])
    assert code == 0
    assert "L2-14" in output
    assert "cfs running at 1 turnouts" in output


def test_the_policy_words_are_checked_on_their_own() -> None:
    assert check_policy("by-leg").value == "by_leg"
    with pytest.raises(PolicyError, match="not a loss rule"):
        check_policy("by-guess")


def test_the_journal_prints_what_was_posted(district: Path) -> None:
    from headgate.audit.journal import EntryKind
    from headgate.store.repo_journal import post

    with Database(district).open() as connection:
        post(
            connection,
            datetime(2025, 7, 1, 8),
            EntryKind.DELIVERY,
            "L2-14",
            "first set",
            volume_af=Decimal("12.5"),
        )
    code, output = run(district, ["report", "journal"])
    assert code == 0
    assert "L2-14" in output
    assert "12.50" in output


def test_an_empty_journal_says_so(district: Path) -> None:
    code, output = run(district, ["report", "journal"])
    assert code == 0
    assert "nothing in the journal answers that" in output


def test_the_journal_can_be_cut_down_to_one_subject(district: Path) -> None:
    from headgate.audit.journal import EntryKind
    from headgate.store.repo_journal import post

    with Database(district).open() as connection:
        post(
            connection,
            datetime(2025, 7, 1, 8),
            EntryKind.DELIVERY,
            "L2-14",
            "first",
            volume_af=Decimal("12.5"),
        )
        post(
            connection,
            datetime(2025, 7, 1, 8),
            EntryKind.DELIVERY,
            "MAIN-3",
            "second",
            volume_af=Decimal("4.5"),
        )
    code, output = run(district, ["report", "journal", "--subject", "MAIN-3"])
    assert code == 0
    assert "MAIN-3" in output
    assert "L2-14" not in output


def add_rights(district: Path) -> None:
    for decree, sequence, year, cfs in (
        ("CDA-1920-1", 1, 1873, "6"),
        ("CDA-1920-5", 5, 1901, "5"),
    ):
        run(
            district,
            [
                "right",
                "add",
                "--decree",
                decree,
                "--owner",
                f"Owner {sequence}",
                "--appropriated",
                f"{year}-05-01",
                "--sequence",
                str(sequence),
                "--mile",
                "20",
                "--rate",
                cfs,
            ],
        )


def test_the_day_report_lists_the_ladder(district: Path) -> None:
    add_rights(district)
    code, output = run(
        district,
        [
            "report",
            "day",
            "--on",
            "2025-07-04",
            "--flow",
            "20",
            "--taking",
            "CDA-1920-1=6",
            "--taking",
            "CDA-1920-5=5",
        ],
    )
    assert code == 0
    assert "CDA-1920-1" in output
    assert "diverted" in output


def test_a_right_over_its_decree_shows_on_the_day_report(district: Path) -> None:
    add_rights(district)
    code, output = run(
        district,
        ["report", "day", "--on", "2025-07-04", "--flow", "20", "--taking", "CDA-1920-5=9"],
    )
    assert code == 0
    assert "rights are over what they are allowed" in output


def test_a_diversion_written_wrong_is_refused_on_the_day_report(district: Path) -> None:
    add_rights(district)
    code, output = run(
        district,
        ["report", "day", "--on", "2025-07-04", "--flow", "20", "--taking", "CDA-1920-5"],
    )
    assert code != 0
    assert "write it as decree=cfs" in output


def test_an_account_statement_prints_the_water_and_the_money(district: Path) -> None:
    code, output = run(
        district,
        ["report", "account", "--account", "118", "--year", "2025", "--as-of", "2025-12-15"],
    )
    assert code == 0
    assert "Holder 118" in output
    assert "acre feet" in output
    assert "standing" in output


def test_an_account_delivered_nowhere_has_no_statement(district: Path) -> None:
    run(
        district,
        ["account", "add", "--number", "999", "--name", "Nobody", "--joined", "2020-01-01"],
    )
    code, output = run(district, ["report", "account", "--account", "999", "--year", "2025"])
    assert code != 0
    assert "not delivered anywhere" in output
