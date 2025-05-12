"""The office's year, driven the way the office drives it.

Everything in this file goes through the command line, because that is the only
interface the district has and because a command that works in a unit test and
fails on the real path is the failure this suite exists to catch. It builds a
district from nothing, runs a season, closes it, finds a weir reading high,
restates the season, and compares the two years.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

import pytest

from tests.support.district import init_book, must


def build(book: Path) -> None:
    must(
        book,
        [
            "ditch",
            "add",
            "--code",
            "MAIN",
            "--name",
            "Sanpete Main Canal",
            "--capacity",
            "48",
            "--length",
            "26400",
            "--loss",
            "0.02",
            "--diversion-mile",
            "28.4",
        ],
    )
    must(
        book,
        [
            "ditch",
            "add",
            "--code",
            "L2",
            "--name",
            "Second Lateral",
            "--capacity",
            "12",
            "--length",
            "10560",
            "--loss",
            "0.05",
            "--parent",
            "MAIN",
            "--offtake",
            "15840",
        ],
    )
    must(
        book,
        [
            "ditch",
            "turnout",
            "--ditch",
            "MAIN",
            "--code",
            "MAIN-3",
            "--name",
            "Bench gate",
            "--station",
            "5280",
            "--capacity",
            "8",
            "--acres",
            "60",
        ],
    )
    must(
        book,
        [
            "ditch",
            "turnout",
            "--ditch",
            "L2",
            "--code",
            "L2-14",
            "--name",
            "Lower gate",
            "--station",
            "5280",
            "--capacity",
            "6",
            "--acres",
            "40",
        ],
    )
    must(
        book,
        ["account", "add", "--number", "118", "--name", "Alma Peterson", "--joined", "1994-03-01"],
    )
    must(
        book,
        ["account", "add", "--number", "212", "--name", "Ruth Larsen", "--joined", "1998-05-01"],
    )
    must(
        book,
        [
            "account",
            "issue",
            "--serial",
            "A-1001",
            "--account",
            "118",
            "--shares",
            "24",
            "--turnout",
            "MAIN-3",
            "--issued",
            "2005-04-01",
        ],
    )
    must(
        book,
        [
            "account",
            "issue",
            "--serial",
            "A-1002",
            "--account",
            "212",
            "--shares",
            "16",
            "--turnout",
            "L2-14",
            "--issued",
            "2005-04-01",
        ],
    )
    for tag, turnout, crest in (("WEIR-MAIN-3", "MAIN-3", "4"), ("WEIR-L2-14", "L2-14", "3")):
        must(
            book,
            [
                "device",
                "install",
                "--tag",
                tag,
                "--kind",
                "cipolletti-weir",
                "--installed",
                "2016-03-01",
                "--turnout",
                turnout,
                "--crest",
                crest,
            ],
        )
    must(
        book,
        [
            "device",
            "install",
            "--tag",
            "FLUME-MAIN",
            "--kind",
            "parshall-flume",
            "--installed",
            "2011-05-01",
            "--ditch",
            "MAIN",
            "--throat",
            "6",
        ],
    )


def open_season(book: Path, year: int) -> None:
    must(
        book,
        [
            "season",
            "declare",
            "--year",
            str(year),
            "--opens",
            f"{year}-04-15",
            "--closes",
            f"{year}-10-01",
            "--declared",
            f"{year}-03-20",
        ],
    )
    must(
        book,
        [
            "season",
            "rates",
            "--year",
            str(year),
            "--per-share",
            "6.00",
            "--band",
            "50:2.00",
            "--band",
            "200:3.50",
            "--band",
            "open:6.00",
            "--adopted",
            f"{year}-03-20",
        ],
    )
    for tag in ("WEIR-MAIN-3", "WEIR-L2-14", "FLUME-MAIN"):
        must(
            book,
            [
                "device",
                "calibrate",
                "--tag",
                tag,
                "--on",
                f"{year}-04-10",
                "--by",
                "R. Aldrich",
                "--months",
                "12",
            ],
        )


def readings(book: Path, path: Path, year: int, bench: str, lower: str, canal: str) -> None:
    rows = ["device,taken_at,observer,head,note"]
    start = datetime(year, 4, 15, 6)
    for tag, head in (
        ("WEIR-MAIN-3", bench),
        ("WEIR-L2-14", lower),
        ("FLUME-MAIN", canal),
    ):
        for index in range(16):
            when = start + timedelta(days=index * 10)
            rows.append(f"{tag},{when:%Y-%m-%dT%H:%M},D. Yardley,{head},")
    path.write_text("\n".join(rows) + "\n", encoding="utf-8")
    must(book, ["reading", "import", str(path)])


@pytest.fixture
def district(tmp_path: Path) -> Path:
    book = init_book(tmp_path / "district.sqlite3")
    build(book)
    open_season(book, 2025)
    readings(book, tmp_path / "2025.csv", 2025, "0.80", "0.55", "1.50")
    return book


def test_the_book_checks_out_after_it_is_built(district: Path) -> None:
    output = must(district, ["check", "--on", "2025-06-01"])
    assert "nothing wrong with the book" in output


def test_the_season_reports_before_it_is_closed(district: Path) -> None:
    output = must(district, ["report", "season", "2025"])
    assert "MAIN-3" in output
    assert "L2-14" in output


def test_an_order_runs_from_placing_to_the_run_sheet(district: Path) -> None:
    must(
        district,
        [
            "order",
            "place",
            "--account",
            "212",
            "--turnout",
            "L2-14",
            "--rate",
            "2.5",
            "--from",
            "2025-07-01T06:00",
            "--to",
            "2025-07-08T06:00",
            "--placed",
            "2025-06-28T08:00",
        ],
    )
    answered = must(district, ["order", "answer", "1"])
    assert "accepted" in answered
    sheet = must(district, ["report", "runsheet", "--on", "2025-07-04", "--at", "2025-07-04T12:00"])
    assert "L2-14" in sheet


def test_closing_the_season_bills_both_accounts(district: Path) -> None:
    output = must(district, ["season", "close", "--year", "2025", "--issued", "2025-11-01"])
    assert "2 bills written" in output
    statement = must(
        district,
        ["report", "account", "--account", "118", "--year", "2025", "--as-of", "2025-12-15"],
    )
    assert "Alma Peterson" in statement
    assert "billed" in statement


def test_a_payment_clears_the_account(district: Path) -> None:
    must(district, ["season", "close", "--year", "2025", "--issued", "2025-11-01"])
    statement = must(
        district,
        ["report", "account", "--account", "118", "--year", "2025", "--as-of", "2025-12-15"],
    )
    assert "in good standing" in statement
    must(
        district, ["account", "pay", "--account", "118", "--amount", "50.00", "--on", "2025-11-20"]
    )
    after = must(
        district,
        ["report", "account", "--account", "118", "--year", "2025", "--as-of", "2025-12-15"],
    )
    assert "paid" in after


def test_a_weir_reading_high_restates_the_season(district: Path) -> None:
    must(district, ["season", "close", "--year", "2025", "--issued", "2025-11-01"])
    output = must(
        district,
        [
            "season",
            "restate",
            "--year",
            "2025",
            "--device",
            "WEIR-L2-14",
            "--offset",
            "-0.05",
            "--found",
            "2025-09-15",
            "--by",
            "R. Aldrich",
            "--reason",
            "staff read high",
            "--issued",
            "2026-01-15",
            "--board-approved",
        ],
    )
    assert "written and posted" in output
    journal = must(district, ["report", "journal", "--kind", "restatement"])
    assert "restatement" in journal


def test_two_seasons_compare_after_the_second_one_is_read(district: Path, tmp_path: Path) -> None:
    open_season(district, 2026)
    readings(district, tmp_path / "2026.csv", 2026, "0.55", "0.35", "1.10")
    output = must(district, ["report", "compare", "--from", "2025", "--to", "2026"])
    assert "2025 to 2026" in output
    assert "delivered" in output


def test_the_journal_holds_what_the_close_posted(district: Path) -> None:
    must(district, ["season", "close", "--year", "2025", "--issued", "2025-11-01"])
    output = must(district, ["report", "journal", "--kind", "delivery"])
    assert "MAIN-3" in output
    assert "delivery" in output


def test_the_book_backs_up_and_verifies_after_a_season(district: Path, tmp_path: Path) -> None:
    must(district, ["season", "close", "--year", "2025", "--issued", "2025-11-01"])
    destination = tmp_path / "backup.sqlite3"
    must(district, ["backup", str(destination)])
    assert "is sound" in must(district, ["verify", str(destination)])


def test_the_exception_report_is_quiet_on_a_clean_season(district: Path) -> None:
    output = must(district, ["report", "exceptions", "--year", "2025", "--on", "2025-06-01"])
    assert "MAIN-3" in output or "nothing wants doing" in output
