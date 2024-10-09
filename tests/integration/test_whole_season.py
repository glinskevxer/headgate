"""A district set up from nothing, run for a season, and closed.

This is the test that would have caught every integration bug the unit tests
were individually happy about. It builds the book through the command line the
way an office would, loads a season of readings, and then closes the year the
way the clerk does in November, checking that the report and the bills come off
the same water.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest
from click.testing import CliRunner

from headgate.assessment.tiers import Band, RateSchedule
from headgate.carriage.apportion import LossPolicy
from headgate.cli.main import main
from headgate.ids import AccountNumber, TurnoutCode
from headgate.measure.quality import Provenance
from headgate.money import Money
from headgate.season.close import close_season
from headgate.store.assemble import build_ledger, headgate_volume
from headgate.store.db import Database
from headgate.store.repo_accounts import load_register
from headgate.store.repo_ditch import load_system
from headgate.store.repo_season import load_season

BENCH = TurnoutCode("MAIN-3")
LOWER = TurnoutCode("L2-14")
FAR = TurnoutCode("L2-20")
PETERSON = AccountNumber(118)
LARSEN = AccountNumber(212)


def run(book: Path, arguments: list[str]) -> tuple[int, str]:
    result = CliRunner().invoke(main, ["--book", str(book), *arguments])
    return result.exit_code, result.output


def must(book: Path, arguments: list[str]) -> str:
    code, output = run(book, arguments)
    assert code == 0, f"{arguments} failed: {output}"
    return output


def build_district(book: Path) -> None:
    must(
        book,
        ["init", "--name", "Sanpete Ditch Company", "--state", "ut", "--stream", "Sanpete Creek"],
    )
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
        [
            "ditch",
            "turnout",
            "--ditch",
            "L2",
            "--code",
            "L2-20",
            "--name",
            "Tail gate",
            "--station",
            "10560",
            "--capacity",
            "4",
            "--acres",
            "25",
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
    must(
        book,
        [
            "account",
            "issue",
            "--serial",
            "A-1003",
            "--account",
            "212",
            "--shares",
            "8",
            "--turnout",
            "L2-20",
            "--issued",
            "2011-04-01",
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
            "--note",
            "board voted 5 to 0",
        ],
    )
    for tag, turnout, crest in (
        ("WEIR-MAIN-3", "MAIN-3", "4"),
        ("WEIR-L2-14", "L2-14", "3"),
        ("WEIR-L2-20", "L2-20", "2"),
    ):
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
                "calibrate",
                "--tag",
                tag,
                "--on",
                "2025-04-10",
                "--by",
                "R. Aldrich",
                "--offset",
                "0.01",
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
    must(
        book,
        ["device", "calibrate", "--tag", "FLUME-MAIN", "--on", "2025-04-10", "--by", "R. Aldrich"],
    )


def readings_file(path: Path, lapsed_weir: bool = False) -> Path:
    """A season of readings, one trip every ten days, running off as it goes."""

    rows = ["device,taken_at,observer,head,note"]
    start = datetime(2025, 4, 15, 6)
    peaks = {
        "WEIR-MAIN-3": Decimal("0.95"),
        "WEIR-L2-14": Decimal("0.64"),
        "WEIR-L2-20": Decimal("0.42"),
        "FLUME-MAIN": Decimal("1.65"),
    }
    trips = 17
    for tag, peak in peaks.items():
        for index in range(trips):
            when = start + timedelta(days=index * 10)
            if lapsed_weir and tag == "WEIR-L2-14" and index > 5:
                continue
            head = (peak * (Decimal("1") - Decimal(index) / Decimal("40"))).quantize(
                Decimal("0.01")
            )
            rows.append(f"{tag},{when:%Y-%m-%dT%H:%M},D. Yardley,{head},")
    path.write_text("\n".join(rows) + "\n", encoding="utf-8")
    return path


def schedule() -> RateSchedule:
    return RateSchedule(
        water_year=2025,
        per_share=Money.from_dollars("6.00"),
        bands=(
            Band(Decimal("50"), Money.from_dollars("2.00")),
            Band(Decimal("200"), Money.from_dollars("3.50")),
            Band(None, Money.from_dollars("6.00")),
        ),
    )


@pytest.fixture
def district(tmp_path: Path) -> Path:
    book = tmp_path / "district.sqlite3"
    build_district(book)
    must(book, ["reading", "import", str(readings_file(tmp_path / "readings.csv"))])
    return book


def test_the_district_reports_itself_after_it_is_built(district: Path) -> None:
    output = must(district, ["status"])
    assert "Sanpete Ditch Company" in output
    assert "pending:  0" in output


def test_the_season_report_runs_end_to_end(district: Path) -> None:
    output = must(district, ["report", "season", "2025"])
    assert "MAIN-3" in output
    assert "L2-20" in output
    assert "carriage" in output


def test_the_only_gap_is_the_morning_before_the_first_reading(district: Path) -> None:
    output = must(district, ["report", "gaps", "2025"])
    assert "6.00 hours unaccounted for" in output
    assert "nothing measuring it" not in output


def test_an_order_runs_through_intake_and_shows_as_running(district: Path) -> None:
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
            "3",
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
    running = must(district, ["report", "running", "--at", "2025-07-04T12:00"])
    assert "L2-14" in running


def test_the_season_closes_off_the_same_water_the_report_shows(district: Path) -> None:
    with Database(district).open() as connection:
        season = load_season(connection, 2025)
        span = season.as_span()
        ledger = build_ledger(connection, span)
        headgate = headgate_volume(connection, span)
        system = load_system(connection)
        register = load_register(connection)
        shares = {
            holder.number: register.shares_of(holder.number, season.opened)
            for holder in register.accounts
        }
        closed = close_season(
            water_year=2025,
            district="Sanpete Ditch Company",
            ledger=ledger,
            headgate_af=headgate.total_af,
            system=system,
            schedule=schedule(),
            turnout_accounts={BENCH: PETERSON, LOWER: LARSEN, FAR: LARSEN},
            shares=shares,
            issued_on=date(2025, 11, 1),
            policy=LossPolicy.BY_LEG,
        )
    assert closed.report.delivered_af == ledger.total_af
    assert closed.report.headgate_af == headgate.total_af
    assert closed.billed.cents > 0
    assert closed.report.proved_share == Decimal("1.000")


def test_the_far_turnout_carries_the_most_loss(district: Path) -> None:
    with Database(district).open() as connection:
        span = load_season(connection, 2025).as_span()
        ledger = build_ledger(connection, span)
        headgate = headgate_volume(connection, span)
        system = load_system(connection)
        closed = close_season(
            water_year=2025,
            district="Sanpete Ditch Company",
            ledger=ledger,
            headgate_af=headgate.total_af,
            system=system,
            schedule=schedule(),
            turnout_accounts={BENCH: PETERSON, LOWER: LARSEN, FAR: LARSEN},
            shares={PETERSON: Decimal("24"), LARSEN: Decimal("24")},
            issued_on=date(2025, 11, 1),
        )
    assert closed.report.line_for(FAR).loss_af > Decimal("0")
    assert closed.account_season(LARSEN).loss_af > closed.account_season(PETERSON).loss_af


def test_a_turnout_nobody_read_after_june_leaves_a_hole(tmp_path: Path) -> None:
    book = tmp_path / "short.sqlite3"
    build_district(book)
    must(book, ["reading", "import", str(readings_file(tmp_path / "short.csv", True))])
    output = must(book, ["report", "gaps", "2025"])
    assert "L2-14" in output
    with Database(book).open() as connection:
        span = load_season(connection, 2025).as_span()
        ledger = build_ledger(connection, span)
    lower = ledger.for_turnout(LOWER)
    bench = ledger.for_turnout(BENCH)
    assert lower.provenance is Provenance.VOID
    assert lower.unaccounted_hours > bench.unaccounted_hours
    assert lower.unaccounted_hours > Decimal("1000")
    assert lower.total_af > Decimal("0")


def test_the_bills_add_up_to_what_the_run_says(district: Path) -> None:
    with Database(district).open() as connection:
        span = load_season(connection, 2025).as_span()
        ledger = build_ledger(connection, span)
        headgate = headgate_volume(connection, span)
        closed = close_season(
            water_year=2025,
            district="Sanpete Ditch Company",
            ledger=ledger,
            headgate_af=headgate.total_af,
            system=load_system(connection),
            schedule=schedule(),
            turnout_accounts={BENCH: PETERSON, LOWER: LARSEN, FAR: LARSEN},
            shares={PETERSON: Decimal("24"), LARSEN: Decimal("24")},
            issued_on=date(2025, 11, 1),
        )
    total = Money.zero()
    for account in closed.bills.accounts:
        total = total + closed.bill_for(account).total
    assert total == closed.billed
