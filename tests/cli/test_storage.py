from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
from click.testing import CliRunner

from headgate.cli.main import main
from headgate.ids import AccountNumber, DecreeNumber, TurnoutCode
from headgate.model.account import Account, AccountStatus, ShareCertificate, ShareRegister
from headgate.model.ditch import Ditch, DitchSystem, Turnout
from headgate.model.right import Priority, RightKind, WaterRight
from headgate.store.db import Database
from headgate.store.repo_accounts import save_register
from headgate.store.repo_ditch import save_system
from headgate.store.repo_rights import save_right

TURNOUT = TurnoutCode("L2-14")
DECREE = DecreeNumber("CDA-1920-40")


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
            "Sanpete",
            "--state",
            "ut",
            "--stream",
            "Sanpete Creek",
        ],
    )
    with Database(book).open() as connection:
        save_system(
            connection,
            DitchSystem(
                ditches=(
                    Ditch(
                        code=__import__("headgate.ids", fromlist=["DitchCode"]).DitchCode("L2"),
                        name="Second Lateral",
                        capacity_cfs=Decimal("12"),
                        length_feet=Decimal("10560"),
                        loss_fraction_per_mile=Decimal("0.05"),
                        turnouts=(
                            Turnout(
                                TURNOUT, "Lower gate", Decimal("5280"), Decimal("6"), Decimal("40")
                            ),
                        ),
                        diversion_mile=Decimal("28.4"),
                    ),
                )
            ),
        )
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
        save_register(
            connection,
            ShareRegister(
                accounts=(
                    Account(
                        AccountNumber(118), "Alma Peterson", date(1994, 3, 1), AccountStatus.ACTIVE
                    ),
                    Account(
                        AccountNumber(212), "Ruth Larsen", date(1998, 5, 1), AccountStatus.ACTIVE
                    ),
                ),
                certificates=(
                    ShareCertificate(
                        "A-1001", AccountNumber(118), Decimal("30"), TURNOUT, date(2005, 4, 1)
                    ),
                    ShareCertificate(
                        "A-1002", AccountNumber(212), Decimal("10"), TURNOUT, date(2005, 4, 1)
                    ),
                ),
            ),
        )
    return book


def run(book: Path, arguments: list[str]) -> tuple[int, str]:
    result = CliRunner().invoke(main, ["--book", str(book), *arguments])
    return result.exit_code, result.output


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
