from datetime import date
from pathlib import Path

import pytest

from headgate.store.db import Database
from headgate.store.repo_season import declare_season
from headgate.wateryear import IrrigationSeason
from tests.support.district import init_book, lateral, run, shareholders, stock


@pytest.fixture
def district(tmp_path: Path) -> Path:
    book = stock(init_book(tmp_path / "district.sqlite3"), lateral(), shareholders("30", "10"))
    with Database(book).open() as connection:
        declare_season(connection, IrrigationSeason.default_for(2025), date(2025, 3, 20))
    return book


def set_allotment(district: Path, available: str = "800") -> tuple[int, str]:
    return run(
        district,
        [
            "allotment",
            "set",
            "--year",
            "2025",
            "--available",
            available,
            "--basis",
            "April forecast at 70 percent",
            "--on",
            "2025-04-01",
        ],
    )


def test_the_allotment_is_set_from_a_supply(district: Path) -> None:
    code, output = set_allotment(district)
    assert code == 0
    assert "20.00 acre feet a share" in output


def test_the_duty_caps_a_generous_year(district: Path) -> None:
    code, output = run(
        district,
        [
            "allotment",
            "set",
            "--year",
            "2025",
            "--available",
            "8000",
            "--basis",
            "wet year",
            "--on",
            "2025-04-01",
            "--duty",
            "40",
        ],
    )
    assert code == 0
    assert "40.00 acre feet a share" in output


def test_a_district_with_no_shares_cannot_set_an_allotment(tmp_path: Path) -> None:
    book = stock(init_book(tmp_path / "bare.sqlite3"), lateral())
    with Database(book).open() as connection:
        declare_season(connection, IrrigationSeason.default_for(2025), date(2025, 3, 20))
    code, output = set_allotment(book)
    assert code != 0
    assert "nobody held shares" in output


def test_the_allotment_prints_back_with_every_account(district: Path) -> None:
    set_allotment(district)
    code, output = run(district, ["allotment", "show", "--year", "2025"])
    assert code == 0
    assert "00118" in output
    assert "600.00" in output


def test_water_taken_comes_off_what_is_left(district: Path) -> None:
    set_allotment(district)
    code, output = run(
        district, ["allotment", "take", "--year", "2025", "--account", "118", "--volume", "150"]
    )
    assert code == 0
    assert "450.00 acre feet" in output


def test_an_account_cannot_take_more_than_it_has(district: Path) -> None:
    set_allotment(district)
    code, output = run(
        district, ["allotment", "take", "--year", "2025", "--account", "118", "--volume", "900"]
    )
    assert code != 0
    assert "allotment left" in output


def test_one_account_can_be_shown_on_its_own(district: Path) -> None:
    set_allotment(district)
    run(district, ["allotment", "take", "--year", "2025", "--account", "118", "--volume", "150"])
    code, output = run(district, ["allotment", "show", "--year", "2025", "--account", "118"])
    assert code == 0
    assert "used" in output
    assert "150.00" in output


def test_the_allotment_can_be_cut(district: Path) -> None:
    set_allotment(district)
    code, output = run(
        district,
        [
            "allotment",
            "revise",
            "--year",
            "2025",
            "--per-share",
            "12",
            "--on",
            "2025-08-01",
            "--basis",
            "creek quit",
        ],
    )
    assert code == 0
    assert "revision 1" in output


def test_the_allotment_may_not_be_raised_late(district: Path) -> None:
    set_allotment(district)
    code, output = run(
        district,
        [
            "allotment",
            "revise",
            "--year",
            "2025",
            "--per-share",
            "30",
            "--on",
            "2025-08-01",
            "--basis",
            "late storm",
        ],
    )
    assert code != 0
    assert "may not be raised after" in output


def test_a_cut_can_leave_an_account_over_its_allotment(district: Path) -> None:
    set_allotment(district)
    run(district, ["allotment", "take", "--year", "2025", "--account", "118", "--volume", "500"])
    run(
        district,
        [
            "allotment",
            "revise",
            "--year",
            "2025",
            "--per-share",
            "12",
            "--on",
            "2025-08-01",
            "--basis",
            "creek quit",
        ],
    )
    code, output = run(district, ["allotment", "show", "--year", "2025"])
    assert code == 0
    assert "over their allotment" in output


def test_a_year_with_no_allotment_says_so(district: Path) -> None:
    code, output = run(district, ["allotment", "show", "--year", "2024"])
    assert code != 0
    assert "no allotment" in output
