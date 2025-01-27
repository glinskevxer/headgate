from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from headgate.ids import DecreeNumber
from headgate.model.right import Priority, RightKind, WaterRight
from headgate.model.stream import Reach, Stream
from headgate.store.db import Database
from headgate.store.repo_ditch import save_stream
from headgate.store.repo_rights import save_right
from tests.support.district import init_book, lateral, run, stock

SENIOR = DecreeNumber("CDA-1920-1")
JUNIOR = DecreeNumber("CDA-1920-5")
NEARER = DecreeNumber("CDA-1920-4")


def right(decree: DecreeNumber, sequence: int, year: int, mile: str, cfs: str) -> WaterRight:
    return WaterRight(
        decree=decree,
        owner=f"Owner {sequence}",
        kind=RightKind.DIRECT_FLOW,
        priority=Priority(date(year, 5, 1), 1920, sequence),
        diversion_mile=Decimal(mile),
        rate_cfs=Decimal(cfs),
    )


@pytest.fixture
def district(tmp_path: Path) -> Path:
    book = stock(init_book(tmp_path / "district.sqlite3"), lateral())
    with Database(book).open() as connection:
        save_stream(
            connection,
            Stream(
                name="Sanpete Creek",
                reaches=(
                    Reach(
                        "R1", "Upper", Decimal("40"), Decimal("20"), Decimal("2"), Decimal("0.01")
                    ),
                    Reach(
                        "R2", "Lower", Decimal("20"), Decimal("4"), Decimal("3"), Decimal("0.01")
                    ),
                ),
            ),
        )
        save_right(connection, right(SENIOR, 1, 1873, "10", "6"))
        save_right(connection, right(NEARER, 4, 1895, "22", "4"))
        save_right(connection, right(JUNIOR, 5, 1901, "30", "5"))
    return book


def place(district: Path, arriving: str = "2", extra: list[str] | None = None) -> tuple[int, str]:
    arguments = [
        "call",
        "place",
        "--decree",
        "CDA-1920-1",
        "--arriving",
        arriving,
        "--taking",
        "CDA-1920-5=5",
        "--taking",
        "CDA-1920-4=4",
        "--at",
        "2025-07-04T12:00",
        "--stream",
        "Sanpete Creek",
    ]
    return run(district, arguments + (extra or []))


def test_a_short_senior_right_gets_its_juniors_shut(district: Path) -> None:
    code, output = place(district)
    assert code == 0
    assert "honoured" in output
    assert "CDA-1920-5" in output


def test_a_right_getting_its_water_has_nothing_to_call_for(district: Path) -> None:
    code, output = place(district, arriving="6")
    assert code == 0
    assert "unnecessary" in output


def test_a_diversion_written_wrong_is_refused(district: Path) -> None:
    code, output = run(
        district,
        [
            "call",
            "place",
            "--decree",
            "CDA-1920-1",
            "--arriving",
            "2",
            "--taking",
            "CDA-1920-5",
            "--stream",
            "Sanpete Creek",
        ],
    )
    assert code != 0
    assert "write it as decree=cfs" in output


def test_a_call_by_a_right_that_is_not_there_is_refused(district: Path) -> None:
    code, output = run(
        district,
        ["call", "place", "--decree", "CDA-1920-9", "--arriving", "2", "--stream", "Sanpete Creek"],
    )
    assert code != 0
    assert "no decree" in output


def test_nothing_is_standing_before_a_call_is_served(district: Path) -> None:
    code, output = run(district, ["call", "standing", "--at", "2025-07-06T12:00"])
    assert code == 0
    assert "nothing was curtailed" in output


def test_serving_a_call_puts_notices_in_the_book(district: Path) -> None:
    code, output = place(district, extra=["--serve"])
    assert code == 0
    assert "notices served" in output
    code, output = run(district, ["call", "standing", "--at", "2025-07-06T12:00"])
    assert code == 0
    assert "CDA-1920-5" in output
    assert "CDA-1920-1" in output


def test_serving_the_same_call_twice_is_refused(district: Path) -> None:
    place(district, extra=["--serve"])
    code, output = place(district, extra=["--serve"])
    assert code != 0
    assert "already" in output


def test_a_futile_call_serves_nothing(district: Path) -> None:
    code, output = run(
        district,
        [
            "call",
            "place",
            "--decree",
            "CDA-1920-1",
            "--arriving",
            "2",
            "--taking",
            "CDA-1920-4=4",
            "--at",
            "2025-07-04T12:00",
            "--needed-by",
            "2025-07-04T12:30",
            "--stream",
            "Sanpete Creek",
            "--serve",
        ],
    )
    assert code != 0
    assert "futile" in output


def test_lifting_a_call_takes_the_notices_off(district: Path) -> None:
    place(district, extra=["--serve"])
    code, output = run(
        district, ["call", "lift", "--decree", "CDA-1920-1", "--at", "2025-07-20T08:00"]
    )
    assert code == 0
    assert "notices lifted" in output
    code, output = run(district, ["call", "standing", "--at", "2025-07-21T12:00"])
    assert "nothing was curtailed" in output


def test_lifting_a_call_nobody_served_says_so(district: Path) -> None:
    code, output = run(
        district, ["call", "lift", "--decree", "CDA-1920-1", "--at", "2025-07-20T08:00"]
    )
    assert code == 0
    assert "no notices were standing" in output
