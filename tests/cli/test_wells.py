from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from headgate.ids import DecreeNumber
from headgate.model.right import Priority, RightKind, WaterRight
from headgate.store.db import Database
from headgate.store.repo_rights import save_right
from tests.support.district import init_book, lateral, run, stock

DECREE = DecreeNumber("CDA-1972-14")


@pytest.fixture
def district(tmp_path: Path) -> Path:
    book = stock(init_book(tmp_path / "district.sqlite3"), lateral())
    with Database(book).open() as connection:
        save_right(
            connection,
            WaterRight(
                decree=DECREE,
                owner="Alma Peterson",
                kind=RightKind.DIRECT_FLOW,
                priority=Priority(date(1968, 5, 1), 1972, 14),
                diversion_mile=Decimal("21"),
                rate_cfs=Decimal("2"),
            ),
        )
    return book


def add_well(district: Path, distance: str = "1500", limit: str = "200") -> tuple[int, str]:
    return run(
        district,
        [
            "well",
            "add",
            "--id",
            "W-14",
            "--decree",
            "CDA-1972-14",
            "--distance",
            distance,
            "--storativity",
            "0.15",
            "--transmissivity",
            "15000",
            "--capacity",
            "900",
            "--limit",
            limit,
        ],
    )


def pump(district: Path, month: int, volume: str) -> tuple[int, str]:
    return run(
        district,
        [
            "well",
            "pumped",
            "--id",
            "W-14",
            "--year",
            "2025",
            "--month",
            str(month),
            "--volume",
            volume,
        ],
    )


def test_a_well_is_added_with_its_depletion_factor(district: Path) -> None:
    code, output = add_well(district)
    assert code == 0
    assert "depletion factor" in output


def test_a_well_by_the_bridge_is_administered_as_a_diversion(district: Path) -> None:
    code, output = add_well(district, distance="200")
    assert code == 0
    assert "as a diversion: yes" in output


def test_a_well_against_a_decree_that_is_not_there_is_refused(district: Path) -> None:
    code, output = run(
        district,
        [
            "well",
            "add",
            "--id",
            "W-99",
            "--decree",
            "CDA-1972-99",
            "--distance",
            "1500",
            "--storativity",
            "0.15",
            "--transmissivity",
            "15000",
            "--capacity",
            "900",
        ],
    )
    assert code != 0


def test_pumping_is_recorded_and_totalled(district: Path) -> None:
    add_well(district)
    pump(district, 6, "40")
    code, output = pump(district, 7, "60")
    assert code == 0
    assert "100.00 acre feet in 2025" in output


def test_pumping_past_the_decreed_limit_is_refused(district: Path) -> None:
    add_well(district, limit="80")
    pump(district, 6, "40")
    code, output = pump(district, 7, "60")
    assert code != 0
    assert "against a limit" in output


def test_the_depletion_is_worked_month_by_month(district: Path) -> None:
    add_well(district)
    pump(district, 6, "40")
    pump(district, 7, "60")
    code, output = run(
        district,
        ["well", "depletion", "--id", "W-14", "--year", "2025", "--through", "9"],
    )
    assert code == 0
    assert "depleted" in output
    assert "owed" in output


def test_replacing_water_lowers_what_is_owed(district: Path) -> None:
    add_well(district)
    pump(district, 6, "40")
    code, output = run(
        district,
        [
            "well",
            "depletion",
            "--id",
            "W-14",
            "--year",
            "2025",
            "--through",
            "9",
            "--replaced",
            "1000",
        ],
    )
    assert code == 0
    assert "owed      0.00 acre feet" in output


def test_a_well_that_pumped_nothing_has_no_depletion(district: Path) -> None:
    add_well(district)
    code, output = run(
        district, ["well", "depletion", "--id", "W-14", "--year", "2025", "--through", "9"]
    )
    assert code != 0
    assert "pumped nothing" in output


def test_a_plan_that_covers_every_month_says_so(district: Path) -> None:
    add_well(district)
    pump(district, 6, "40")
    pump(district, 7, "60")
    code, output = run(
        district,
        [
            "well",
            "cover",
            "--id",
            "W-14",
            "--year",
            "2025",
            "--through",
            "9",
            "--mile",
            "20",
            "--source",
            "Ephraim storage:26:6=40,7=60,8=60,9=60",
        ],
    )
    assert code == 0
    assert "covers every month" in output


def test_a_plan_short_in_a_month_says_which(district: Path) -> None:
    add_well(district)
    pump(district, 6, "40")
    pump(district, 7, "60")
    code, output = run(
        district,
        [
            "well",
            "cover",
            "--id",
            "W-14",
            "--year",
            "2025",
            "--through",
            "9",
            "--mile",
            "20",
            "--source",
            "Ephraim storage:26:6=40",
        ],
    )
    assert code == 0
    assert "first in month" in output


def test_a_source_below_the_depletion_does_nothing(district: Path) -> None:
    add_well(district)
    pump(district, 6, "40")
    code, output = run(
        district,
        [
            "well",
            "cover",
            "--id",
            "W-14",
            "--year",
            "2025",
            "--through",
            "9",
            "--mile",
            "20",
            "--source",
            "Downstream lease:8:6=400",
        ],
    )
    assert code == 0
    assert "land below the depletion" in output


def test_a_source_written_wrong_is_refused(district: Path) -> None:
    add_well(district)
    pump(district, 6, "40")
    code, output = run(
        district,
        [
            "well",
            "cover",
            "--id",
            "W-14",
            "--year",
            "2025",
            "--through",
            "9",
            "--mile",
            "20",
            "--source",
            "Ephraim storage:26",
        ],
    )
    assert code != 0
    assert "is not a source" in output


def test_the_wells_are_listed(district: Path) -> None:
    add_well(district)
    code, output = run(district, ["well", "list"])
    assert code == 0
    assert "W-14" in output


def test_an_empty_book_lists_no_wells(district: Path) -> None:
    code, output = run(district, ["well", "list"])
    assert code == 0
    assert "no wells yet" in output
