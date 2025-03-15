from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from headgate.ids import TurnoutCode
from headgate.model.ditch import Turnout
from headgate.store.db import Database
from headgate.store.repo_season import declare_season
from headgate.wateryear import IrrigationSeason
from tests.support.district import (
    TURNOUT,
    init_book,
    lateral,
    must,
    run,
    shareholders,
    stock,
)

SECOND = TurnoutCode("L2-20")


@pytest.fixture
def district(tmp_path: Path) -> Path:
    system = lateral(
        (
            Turnout(TURNOUT, "Lower gate", Decimal("5280"), Decimal("6"), Decimal("40")),
            Turnout(SECOND, "Tail gate", Decimal("9000"), Decimal("4"), Decimal("25")),
        )
    )
    book = stock(init_book(tmp_path / "district.sqlite3"), system, shareholders("30", "10"))
    with Database(book).open() as connection:
        declare_season(connection, IrrigationSeason.default_for(2025), date(2025, 3, 20))
        connection.execute("UPDATE certificate SET turnout_code = 'L2-20' WHERE serial = 'A-1002'")
    return book


def build(district: Path, extra: list[str] | None = None) -> tuple[int, str]:
    arguments = [
        "rotation",
        "build",
        "--year",
        "2025",
        "--start",
        "2025-07-01T06:00",
        "--flow",
        "8",
        "--cycle-hours",
        "48",
    ]
    return run(district, arguments + (extra or []))


def test_a_cycle_is_laid_out_from_the_shares(district: Path) -> None:
    code, output = build(district)
    assert code == 0
    assert "windows" in output
    assert "turnouts" in output
    assert output.count("2") >= 2


def test_the_rotation_prints_back(district: Path) -> None:
    build(district)
    code, output = run(district, ["rotation", "show", "--year", "2025"])
    assert code == 0
    assert "L2-14" in output
    assert "hours" in output


def test_a_curtailed_turnout_is_skipped(district: Path) -> None:
    code, output = build(district, ["--curtailed", "L2-20"])
    assert code == 0
    assert "L2-20" in output
    assert "skipped" in output


def test_building_again_replaces_the_year(district: Path) -> None:
    build(district)
    build(district, ["--cycles", "3"])
    code, output = run(district, ["rotation", "show", "--year", "2025"])
    assert output.count("L2-14") >= 3


def test_a_rotation_outside_the_season_is_refused(district: Path) -> None:
    code, output = run(
        district,
        [
            "rotation",
            "build",
            "--year",
            "2025",
            "--start",
            "2025-03-01T06:00",
            "--flow",
            "8",
            "--cycle-hours",
            "48",
        ],
    )
    assert code != 0
    assert "outside the declared season" in output


def test_a_rotation_with_no_water_is_refused(district: Path) -> None:
    code, output = build(district, ["--flow", "0"])
    assert code != 0
    assert "no water to rotate" in output


def test_the_next_turn_is_reported(district: Path) -> None:
    build(district, ["--cycles", "2"])
    code, output = run(
        district, ["rotation", "next", "--turnout", "L2-14", "--after", "2025-07-01T12:00"]
    )
    assert code == 0
    assert "L2-14 runs" in output


def test_a_turnout_that_does_not_come_round_says_so(district: Path) -> None:
    build(district)
    code, output = run(
        district, ["rotation", "next", "--turnout", "L2-14", "--after", "2025-08-01T12:00"]
    )
    assert code != 0
    assert "does not come round again" in output


def test_what_is_running_is_reported(district: Path) -> None:
    build(district)
    code, output = run(district, ["rotation", "running", "--at", "2025-07-01T12:00"])
    assert code == 0
    assert "L2-14 at" in output


def test_nothing_running_says_so(district: Path) -> None:
    build(district)
    code, output = run(district, ["rotation", "running", "--at", "2025-08-01T12:00"])
    assert code == 0
    assert "nothing running" in output


def test_a_year_with_no_rotation_says_so(district: Path) -> None:
    code, output = run(district, ["rotation", "show", "--year", "2024"])
    assert code == 0
    assert "no rotation has been laid out" in output


def test_a_district_with_no_shares_cannot_rotate(tmp_path: Path) -> None:
    book = stock(init_book(tmp_path / "bare.sqlite3"), lateral())
    with Database(book).open() as connection:
        declare_season(connection, IrrigationSeason.default_for(2025), date(2025, 3, 20))
    code, output = run(
        book,
        ["rotation", "build", "--year", "2025", "--start", "2025-07-01T06:00", "--flow", "8"],
    )
    assert code != 0
    assert "nothing to rotate" in output


def test_the_season_has_to_be_declared_first(tmp_path: Path) -> None:
    book = stock(init_book(tmp_path / "nodeclare.sqlite3"), lateral(), shareholders())
    code, output = run(
        book,
        ["rotation", "build", "--year", "2025", "--start", "2025-07-01T06:00", "--flow", "8"],
    )
    assert code != 0
    assert "no season" in output


def test_the_rotation_command_needs_a_book_that_is_set_up(tmp_path: Path) -> None:
    code, output = run(tmp_path / "nothing.sqlite3", ["rotation", "show", "--year", "2025"])
    assert code != 0
    assert "never been set up" in output


def test_must_reports_the_command_it_ran(district: Path) -> None:
    assert "windows" in must(
        district,
        ["rotation", "build", "--year", "2025", "--start", "2025-07-01T06:00", "--flow", "8"],
    )
