"""A season closed, restated, and put in front of the board afterwards.

The restatement is the part of this system that is easiest to get subtly
wrong, because it touches the delivery record, the assessment and the journal
at once and none of them is allowed to be edited. What this checks is that
after it has run, the three of them still say the same thing: the account owes
what the reversal and the replacement add up to, the journal carries both, and
the board packet reads the season with the restatement in it.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest

from headgate.ids import AccountNumber
from headgate.money import Money
from headgate.store.db import Database
from headgate.store.repo_bills import balance_for, bills_for_account
from headgate.store.repo_journal import load_journal
from tests.support.district import init_book, must

PETERSON = AccountNumber(118)


def build(book: Path) -> None:
    must(
        book,
        [
            "ditch",
            "add",
            "--code",
            "MAIN",
            "--name",
            "Main Canal",
            "--capacity",
            "40",
            "--length",
            "21120",
            "--loss",
            "0.02",
            "--diversion-mile",
            "20",
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
            "MAIN-2",
            "--name",
            "Head gate",
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
        [
            "account",
            "issue",
            "--serial",
            "A-1",
            "--account",
            "118",
            "--shares",
            "20",
            "--turnout",
            "MAIN-2",
            "--issued",
            "2005-04-01",
        ],
    )
    must(
        book,
        [
            "season",
            "declare",
            "--year",
            "2025",
            "--opens",
            "2025-04-15",
            "--closes",
            "2025-10-01",
            "--declared",
            "2025-03-20",
        ],
    )
    must(
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
            "open:4.00",
            "--adopted",
            "2025-03-20",
        ],
    )
    must(
        book,
        [
            "device",
            "install",
            "--tag",
            "WEIR-MAIN-2",
            "--kind",
            "cipolletti-weir",
            "--installed",
            "2016-03-01",
            "--turnout",
            "MAIN-2",
            "--crest",
            "3",
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
            "4",
        ],
    )
    for tag in ("WEIR-MAIN-2", "FLUME-MAIN"):
        must(
            book, ["device", "calibrate", "--tag", tag, "--on", "2025-04-10", "--by", "R. Aldrich"]
        )


def readings(book: Path, path: Path) -> None:
    rows = ["device,taken_at,observer,head,note"]
    start = datetime(2025, 4, 15, 6)
    for tag, head in (("WEIR-MAIN-2", "0.60"), ("FLUME-MAIN", "1.20")):
        for index in range(16):
            when = start + timedelta(days=index * 10)
            rows.append(f"{tag},{when:%Y-%m-%dT%H:%M},D. Yardley,{head},")
    path.write_text("\n".join(rows) + "\n", encoding="utf-8")
    must(book, ["reading", "import", str(path)])


@pytest.fixture
def district(tmp_path: Path) -> Path:
    book = init_book(tmp_path / "district.sqlite3")
    build(book)
    readings(book, tmp_path / "readings.csv")
    must(book, ["season", "close", "--year", "2025", "--issued", "2025-11-01"])
    return book


def restate(district: Path, offset: str = "-0.05") -> str:
    return must(
        district,
        [
            "season",
            "restate",
            "--year",
            "2025",
            "--device",
            "WEIR-MAIN-2",
            "--offset",
            offset,
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


def test_the_restatement_leaves_three_bills_in_the_file(district: Path) -> None:
    restate(district)
    with Database(district).open() as connection:
        bills = bills_for_account(connection, PETERSON)
    assert len(bills) == 3


def test_the_balance_is_the_replacement_rather_than_the_sum(district: Path) -> None:
    restate(district)
    with Database(district).open() as connection:
        bills = bills_for_account(connection, PETERSON)
        owed = balance_for(connection, PETERSON)
    original, reversal, replacement = bills
    assert original.total + reversal.total == Money.zero()
    assert owed == replacement.total


def test_a_weir_reading_high_lowers_what_the_account_owes(district: Path) -> None:
    with Database(district).open() as connection:
        before = balance_for(connection, PETERSON)
    restate(district)
    with Database(district).open() as connection:
        after = balance_for(connection, PETERSON)
    assert after < before


def test_the_journal_carries_the_calibration_and_the_restatement(district: Path) -> None:
    restate(district)
    with Database(district).open() as connection:
        journal = load_journal(connection)
    kinds = {entry.kind.value for entry in journal.entries}
    assert "calibration" in kinds
    assert "restatement" in kinds


def test_the_board_packet_reads_the_season_after_the_restatement(district: Path) -> None:
    restate(district)
    output = must(district, ["report", "board", "--year", "2025", "--on", "2025-11-01"])
    assert "recommend adopting" in output
    assert "assessment" in output


def test_the_delivery_record_itself_is_not_edited(district: Path) -> None:
    before = must(district, ["report", "season", "2025"])
    restate(district)
    after = must(district, ["report", "season", "2025"])
    assert before == after


def test_a_second_restatement_of_the_same_season_is_allowed(district: Path) -> None:
    restate(district)
    output = restate(district, offset="-0.06")
    assert "written and posted" in output
    with Database(district).open() as connection:
        assert len(bills_for_account(connection, PETERSON)) == 5


def test_the_log_shows_both_the_close_and_the_restatement(district: Path) -> None:
    restate(district)
    output = must(district, ["log"])
    assert "season close" in output
    assert "season restate" in output


def test_the_book_still_checks_out_afterwards(district: Path) -> None:
    restate(district)
    output = must(district, ["check", "--on", "2025-06-01"])
    assert "nothing wrong with the book" in output


def test_the_restated_volume_is_smaller_than_the_original(district: Path) -> None:
    output = restate(district)
    assert "should be" in output
    assert "change" in output
    assert Decimal("0") > Decimal(
        [line for line in output.splitlines() if line.startswith("change")][0].split()[1]
    )
