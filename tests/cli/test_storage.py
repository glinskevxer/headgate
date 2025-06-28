from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from headgate.ids import DecreeNumber
from headgate.model.right import Priority, RightKind, WaterRight
from headgate.store.db import Database
from headgate.store.repo_rights import save_right
from tests.support.district import init_book, lateral, run, shareholders, stock

DECREE = DecreeNumber("CDA-1920-40")


@pytest.fixture
def district(tmp_path: Path) -> Path:
    book = stock(
        init_book(tmp_path / "district.sqlite3"),
        lateral(),
        shareholders("30", "10"),
    )
    with Database(book).open() as connection:
        save_right(
            connection,
            WaterRight(
                decree=DECREE,
                owner="Sanpete Ditch Company",
                kind=RightKind.STORAGE,
                priority=Priority(date(1911, 5, 1), 1920, 40),
                diversion_mile=Decimal("31"),
                volume_af=Decimal("4000"),
            ),
        )
    return book


def build(book: Path) -> tuple[int, str]:
    return run(
        book,
        [
            "reservoir",
            "build",
            "--name",
            "Ephraim Reservoir",
            "--decree",
            "CDA-1920-40",
            "--capacity",
            "4000",
            "--dead-pool",
            "300",
        ],
    )


def test_a_reservoir_is_built(district: Path) -> None:
    code, output = build(district)
    assert code == 0
    assert "3700.00 of it usable" in output


def test_a_reservoir_against_a_decree_that_is_not_there_is_refused(district: Path) -> None:
    code, _ = run(
        district,
        ["reservoir", "build", "--name", "Other", "--decree", "CDA-1920-99", "--capacity", "100"],
    )
    assert code != 0


def test_filling_stores_water_and_reports_the_pool(district: Path) -> None:
    build(district)
    code, output = run(
        district,
        [
            "reservoir",
            "fill",
            "--name",
            "Ephraim Reservoir",
            "--on",
            "2025-04-01",
            "--inflow",
            "1200",
        ],
    )
    assert code == 0
    assert "1500.00 acre feet" in output
    assert "percent full" in output


def test_filling_past_the_top_spills(district: Path) -> None:
    build(district)
    run(
        district,
        [
            "reservoir",
            "fill",
            "--name",
            "Ephraim Reservoir",
            "--on",
            "2025-04-01",
            "--inflow",
            "3600",
        ],
    )
    code, output = run(
        district,
        [
            "reservoir",
            "fill",
            "--name",
            "Ephraim Reservoir",
            "--on",
            "2025-04-08",
            "--inflow",
            "500",
        ],
    )
    assert code == 0
    assert "spilled" in output


def test_filling_outside_the_season_is_refused(district: Path) -> None:
    build(district)
    code, output = run(
        district,
        [
            "reservoir",
            "fill",
            "--name",
            "Ephraim Reservoir",
            "--on",
            "2025-08-01",
            "--inflow",
            "100",
        ],
    )
    assert code != 0
    assert "outside its fill season" in output


def test_allocating_splits_the_pool_by_shares(district: Path) -> None:
    build(district)
    run(
        district,
        [
            "reservoir",
            "fill",
            "--name",
            "Ephraim Reservoir",
            "--on",
            "2025-04-01",
            "--inflow",
            "1700",
        ],
    )
    code, output = run(
        district,
        [
            "reservoir",
            "allocate",
            "--name",
            "Ephraim Reservoir",
            "--year",
            "2025",
            "--on",
            "2025-04-15",
        ],
    )
    assert code == 0
    assert "2 accounts" in output
    code, output = run(
        district, ["reservoir", "show", "--name", "Ephraim Reservoir", "--year", "2025"]
    )
    assert "00118" in output
    assert "1275.00" in output


def test_drawing_takes_water_out_of_an_account(district: Path) -> None:
    build(district)
    run(
        district,
        [
            "reservoir",
            "fill",
            "--name",
            "Ephraim Reservoir",
            "--on",
            "2025-04-01",
            "--inflow",
            "1700",
        ],
    )
    run(
        district,
        [
            "reservoir",
            "allocate",
            "--name",
            "Ephraim Reservoir",
            "--year",
            "2025",
            "--on",
            "2025-04-15",
        ],
    )
    code, output = run(
        district,
        [
            "reservoir",
            "draw",
            "--name",
            "Ephraim Reservoir",
            "--year",
            "2025",
            "--account",
            "118",
            "--volume",
            "275",
        ],
    )
    assert code == 0
    assert "1000.00 acre feet left" in output


def test_drawing_more_than_an_account_has_is_refused(district: Path) -> None:
    build(district)
    run(
        district,
        [
            "reservoir",
            "fill",
            "--name",
            "Ephraim Reservoir",
            "--on",
            "2025-04-01",
            "--inflow",
            "1700",
        ],
    )
    run(
        district,
        [
            "reservoir",
            "allocate",
            "--name",
            "Ephraim Reservoir",
            "--year",
            "2025",
            "--on",
            "2025-04-15",
        ],
    )
    code, output = run(
        district,
        [
            "reservoir",
            "draw",
            "--name",
            "Ephraim Reservoir",
            "--year",
            "2025",
            "--account",
            "212",
            "--volume",
            "900",
        ],
    )
    assert code != 0
    assert "acre feet stored" in output


def test_showing_a_pool_before_the_allocation_says_so(district: Path) -> None:
    build(district)
    run(
        district,
        [
            "reservoir",
            "fill",
            "--name",
            "Ephraim Reservoir",
            "--on",
            "2025-04-01",
            "--inflow",
            "1200",
        ],
    )
    code, output = run(
        district, ["reservoir", "show", "--name", "Ephraim Reservoir", "--year", "2025"]
    )
    assert code == 0
    assert "nothing allocated yet" in output


def test_showing_a_year_with_no_pool_is_refused(district: Path) -> None:
    build(district)
    code, output = run(
        district, ["reservoir", "show", "--name", "Ephraim Reservoir", "--year", "2025"]
    )
    assert code != 0
    assert "no pool" in output


def filled_and_allocated(district: Path) -> None:
    build(district)
    run(
        district,
        [
            "reservoir",
            "fill",
            "--name",
            "Ephraim Reservoir",
            "--on",
            "2025-04-01",
            "--inflow",
            "1700",
        ],
    )
    run(
        district,
        [
            "reservoir",
            "allocate",
            "--name",
            "Ephraim Reservoir",
            "--year",
            "2025",
            "--on",
            "2025-04-15",
        ],
    )


def test_the_pool_and_the_accounts_carry_into_the_next_year(district: Path) -> None:
    filled_and_allocated(district)
    code, output = run(
        district,
        ["reservoir", "carryover", "--name", "Ephraim Reservoir", "--from", "2025", "--to", "2026"],
    )
    assert code == 0
    assert "carried" in output
    assert "2 accounts" in output
    code, output = run(
        district, ["reservoir", "show", "--name", "Ephraim Reservoir", "--year", "2026"]
    )
    assert code == 0
    assert "00118" in output


def test_water_over_the_cap_is_lost_on_the_way_across(district: Path) -> None:
    filled_and_allocated(district)
    code, output = run(
        district,
        [
            "reservoir",
            "carryover",
            "--name",
            "Ephraim Reservoir",
            "--from",
            "2025",
            "--to",
            "2026",
            "--cap",
            "100",
        ],
    )
    assert code == 0
    assert "over the cap and are gone" in output


def test_carrying_backwards_is_refused(district: Path) -> None:
    filled_and_allocated(district)
    code, output = run(
        district,
        ["reservoir", "carryover", "--name", "Ephraim Reservoir", "--from", "2025", "--to", "2024"],
    )
    assert code != 0
    assert "does not come after" in output


def test_a_pool_with_nothing_allocated_still_carries(district: Path) -> None:
    build(district)
    run(
        district,
        [
            "reservoir",
            "fill",
            "--name",
            "Ephraim Reservoir",
            "--on",
            "2025-04-01",
            "--inflow",
            "800",
        ],
    )
    code, output = run(
        district,
        ["reservoir", "carryover", "--name", "Ephraim Reservoir", "--from", "2025", "--to", "2026"],
    )
    assert code == 0
    assert "nothing allocated behind it" in output


def test_a_year_with_no_pool_cannot_be_carried(district: Path) -> None:
    build(district)
    code, output = run(
        district,
        ["reservoir", "carryover", "--name", "Ephraim Reservoir", "--from", "2025", "--to", "2026"],
    )
    assert code != 0
    assert "no pool" in output
