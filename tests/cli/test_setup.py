from pathlib import Path

import pytest
from click.testing import CliRunner

from headgate.cli.main import main


@pytest.fixture
def book(tmp_path: Path) -> Path:
    path = tmp_path / "district.sqlite3"
    result = CliRunner().invoke(
        main,
        [
            "--book",
            str(path),
            "init",
            "--name",
            "Sanpete Ditch Company",
            "--state",
            "ut",
            "--stream",
            "Sanpete Creek",
        ],
    )
    assert result.exit_code == 0
    return path


def run(book: Path, arguments: list[str]) -> tuple[int, str]:
    result = CliRunner().invoke(main, ["--book", str(book), *arguments])
    return result.exit_code, result.output


def add_main(book: Path) -> tuple[int, str]:
    return run(
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
            "--diversion-mile",
            "28.4",
        ],
    )


def add_lateral(book: Path) -> tuple[int, str]:
    return run(
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


def test_the_main_canal_is_added_first(book: Path) -> None:
    code, output = add_main(book)
    assert code == 0
    assert "ditch MAIN added" in output
    assert "5.00 miles" in output


def test_a_lateral_hangs_off_the_canal(book: Path) -> None:
    add_main(book)
    code, output = add_lateral(book)
    assert code == 0
    assert "ditch L2 added" in output


def test_a_lateral_off_a_ditch_that_is_not_there_is_refused(book: Path) -> None:
    code, output = add_lateral(book)
    assert code != 0
    assert "not here" in output or "one main canal" in output


def test_two_main_canals_are_refused(book: Path) -> None:
    add_main(book)
    code, output = run(
        book,
        [
            "ditch",
            "add",
            "--code",
            "OTHER",
            "--name",
            "Other Canal",
            "--capacity",
            "10",
            "--length",
            "5280",
            "--diversion-mile",
            "20",
        ],
    )
    assert code != 0
    assert "one main canal" in output


def test_a_turnout_is_added_to_a_ditch(book: Path) -> None:
    add_main(book)
    add_lateral(book)
    code, output = run(
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
    assert code == 0
    assert "turnout L2-14 added to L2" in output


def test_a_turnout_on_the_wrong_ditch_is_refused(book: Path) -> None:
    add_main(book)
    add_lateral(book)
    code, output = run(
        book,
        [
            "ditch",
            "turnout",
            "--ditch",
            "MAIN",
            "--code",
            "L2-14",
            "--name",
            "Lower gate",
            "--station",
            "5280",
            "--capacity",
            "6",
        ],
    )
    assert code != 0
    assert "is not on ditch" in output


def test_the_ditches_are_listed(book: Path) -> None:
    add_main(book)
    add_lateral(book)
    code, output = run(book, ["ditch", "list"])
    assert code == 0
    assert "MAIN" in output
    assert "off MAIN" in output


def test_an_empty_book_lists_no_ditches(book: Path) -> None:
    code, output = run(book, ["ditch", "list"])
    assert code == 0
    assert "no ditches yet" in output


def test_an_account_is_added_and_listed(book: Path) -> None:
    code, output = run(
        book,
        [
            "account",
            "add",
            "--number",
            "118",
            "--name",
            "Alma Peterson",
            "--joined",
            "1994-03-01",
            "--mailing",
            "Box 41",
            "--mailing",
            "Manti UT 84642",
        ],
    )
    assert code == 0
    assert "account 00118 added" in output
    code, output = run(book, ["account", "list"])
    assert "Alma Peterson" in output
    assert "active" in output


def test_a_certificate_is_issued_against_a_turnout(book: Path) -> None:
    add_main(book)
    add_lateral(book)
    run(
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
        ],
    )
    run(
        book,
        ["account", "add", "--number", "118", "--name", "Alma Peterson", "--joined", "1994-03-01"],
    )
    code, output = run(
        book,
        [
            "account",
            "issue",
            "--serial",
            "A-1001",
            "--account",
            "118",
            "--shares",
            "20",
            "--turnout",
            "L2-14",
            "--issued",
            "2020-04-01",
        ],
    )
    assert code == 0
    assert "certificate A-1001 issued" in output
    code, output = run(book, ["account", "list", "--on", "2025-06-01"])
    assert "20 shares" in output


def test_a_certificate_for_a_turnout_that_is_not_there_is_refused(book: Path) -> None:
    run(
        book,
        ["account", "add", "--number", "118", "--name", "Alma Peterson", "--joined", "1994-03-01"],
    )
    code, _ = run(
        book,
        [
            "account",
            "issue",
            "--serial",
            "A-1001",
            "--account",
            "118",
            "--shares",
            "20",
            "--turnout",
            "L9-1",
            "--issued",
            "2020-04-01",
        ],
    )
    assert code != 0


def test_an_empty_book_lists_no_accounts(book: Path) -> None:
    code, output = run(book, ["account", "list"])
    assert code == 0
    assert "no accounts yet" in output


def test_the_season_is_declared(book: Path) -> None:
    code, output = run(
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
    assert code == 0
    assert "season 2025 declared" in output
    assert "169 days" in output


def test_declaring_the_same_season_twice_is_refused(book: Path) -> None:
    run(
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
    code, output = run(
        book,
        [
            "season",
            "declare",
            "--year",
            "2025",
            "--opens",
            "2025-04-20",
            "--closes",
            "2025-10-01",
            "--declared",
            "2025-03-21",
        ],
    )
    assert code != 0
    assert "already been declared" in output


def test_a_payment_is_taken_against_an_account(book: Path) -> None:
    run(
        book,
        ["account", "add", "--number", "118", "--name", "Alma Peterson", "--joined", "1994-03-01"],
    )
    code, output = run(
        book,
        [
            "account",
            "pay",
            "--account",
            "118",
            "--amount",
            "90.00",
            "--on",
            "2025-11-20",
            "--reference",
            "cheque 1184",
        ],
    )
    assert code == 0
    assert "payment 1 of $90.00 taken" in output
    assert "-$90.00" in output


def test_a_payment_from_an_account_that_is_not_there_is_refused(book: Path) -> None:
    code, output = run(
        book,
        ["account", "pay", "--account", "999", "--amount", "90.00", "--on", "2025-11-20"],
    )
    assert code != 0
    assert "no account" in output


def test_a_payment_of_nothing_is_refused(book: Path) -> None:
    run(
        book,
        ["account", "add", "--number", "118", "--name", "Alma Peterson", "--joined", "1994-03-01"],
    )
    code, output = run(
        book, ["account", "pay", "--account", "118", "--amount", "0", "--on", "2025-11-20"]
    )
    assert code != 0
    assert "not a payment" in output


def test_the_rate_schedule_is_adopted(book: Path) -> None:
    code, output = run(
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
            "open:3.50",
            "--adopted",
            "2025-03-20",
        ],
    )
    assert code == 0
    assert "2025 rates adopted" in output
    assert "2 bands" in output


def test_a_schedule_with_no_bands_is_refused(book: Path) -> None:
    code, output = run(
        book,
        ["season", "rates", "--year", "2025", "--per-share", "6.00", "--adopted", "2025-03-20"],
    )
    assert code != 0
    assert "at least one band" in output


def test_a_band_written_wrong_is_refused(book: Path) -> None:
    code, output = run(
        book,
        [
            "season",
            "rates",
            "--year",
            "2025",
            "--per-share",
            "6.00",
            "--band",
            "50",
            "--adopted",
            "2025-03-20",
        ],
    )
    assert code != 0
    assert "write it as ceiling:rate" in output


def test_adopting_the_same_year_twice_is_refused(book: Path) -> None:
    run(
        book,
        [
            "season",
            "rates",
            "--year",
            "2025",
            "--per-share",
            "6.00",
            "--band",
            "open:3.50",
            "--adopted",
            "2025-03-20",
        ],
    )
    code, output = run(
        book,
        [
            "season",
            "rates",
            "--year",
            "2025",
            "--per-share",
            "7.00",
            "--band",
            "open:4.00",
            "--adopted",
            "2025-03-21",
        ],
    )
    assert code != 0
    assert "already been adopted" in output


def with_lateral(book: Path) -> Path:
    add_main(book)
    add_lateral(book)
    return book


def seepage_run(book: Path, outflow: str = "9", turnouts: str = "0") -> tuple[int, str]:
    return run(
        book,
        [
            "ditch",
            "seepage",
            "--ditch",
            "L2",
            "--on",
            "2025-05-20",
            "--from-station",
            "0",
            "--to-station",
            "5280",
            "--inflow",
            "10",
            "--outflow",
            outflow,
            "--turnouts",
            turnouts,
            "--note",
            "two flumes",
        ],
    )


def test_a_seepage_run_is_recorded(book: Path) -> None:
    with_lateral(book)
    code, output = seepage_run(book)
    assert code == 0
    assert "lost 1.000 cfs" in output


def test_a_gaining_reach_says_so(book: Path) -> None:
    with_lateral(book)
    code, output = seepage_run(book, outflow="11")
    assert code == 0
    assert "gained 1.000 cfs" in output


def test_a_run_with_the_turnouts_open_says_why_it_is_no_good(book: Path) -> None:
    with_lateral(book)
    code, output = seepage_run(book, outflow="8.5", turnouts="0.5")
    assert code == 0
    assert "running to turnouts" in output


def test_the_loss_report_shows_the_runs(book: Path) -> None:
    with_lateral(book)
    seepage_run(book)
    code, output = run(book, ["ditch", "loss", "--ditch", "L2"])
    assert code == 0
    assert "measured" in output
    assert "losing more than the book says" in output


def test_adopting_the_measured_rate_changes_the_ditch(book: Path) -> None:
    with_lateral(book)
    seepage_run(book)
    code, output = run(book, ["ditch", "loss", "--ditch", "L2", "--adopt"])
    assert code == 0
    assert "now carries" in output


def test_a_ditch_nobody_has_run_says_so(book: Path) -> None:
    with_lateral(book)
    code, output = run(book, ["ditch", "loss", "--ditch", "L2"])
    assert code == 0
    assert "nobody has run a seepage test" in output


def test_a_ditch_with_no_credible_run_adopts_nothing(book: Path) -> None:
    with_lateral(book)
    seepage_run(book, outflow="9.95")
    code, output = run(book, ["ditch", "loss", "--ditch", "L2", "--adopt"])
    assert code == 0
    assert "no run is worth setting a rate from" in output


def test_a_parcel_is_put_under_a_turnout(book: Path) -> None:
    with_lateral(book)
    run(
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
        ],
    )
    run(
        book,
        ["account", "add", "--number", "118", "--name", "Alma Peterson", "--joined", "1994-03-01"],
    )
    code, output = run(
        book,
        [
            "account",
            "parcel",
            "--parcel",
            "11-042-001",
            "--account",
            "118",
            "--turnout",
            "L2-14",
            "--acres",
            "40",
            "--crop",
            "alfalfa",
            "--application",
            "pivot",
        ],
    )
    assert code == 0
    assert "40 acres of alfalfa" in output
    assert "acre feet at the gate" in output


def test_a_pivot_wants_less_at_the_gate_than_flood(book: Path) -> None:
    with_lateral(book)
    run(
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
        ],
    )
    run(
        book,
        ["account", "add", "--number", "118", "--name", "Alma Peterson", "--joined", "1994-03-01"],
    )
    _, flooded = run(
        book,
        [
            "account",
            "parcel",
            "--parcel",
            "11-042-001",
            "--account",
            "118",
            "--turnout",
            "L2-14",
            "--acres",
            "40",
            "--application",
            "flood",
        ],
    )
    _, pivoted = run(
        book,
        [
            "account",
            "parcel",
            "--parcel",
            "11-042-002",
            "--account",
            "118",
            "--turnout",
            "L2-14",
            "--acres",
            "40",
            "--application",
            "pivot",
        ],
    )
    assert flooded != pivoted


def test_a_parcel_can_be_dried_up(book: Path) -> None:
    with_lateral(book)
    run(
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
        ],
    )
    run(
        book,
        ["account", "add", "--number", "118", "--name", "Alma Peterson", "--joined", "1994-03-01"],
    )
    run(
        book,
        [
            "account",
            "parcel",
            "--parcel",
            "11-042-001",
            "--account",
            "118",
            "--turnout",
            "L2-14",
            "--acres",
            "40",
        ],
    )
    code, output = run(book, ["account", "dry-up", "--parcel", "11-042-001", "--on", "2025-07-01"])
    assert code == 0
    assert "is dry from 2025-07-01" in output


def test_drying_up_a_parcel_twice_is_refused(book: Path) -> None:
    with_lateral(book)
    run(
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
        ],
    )
    run(
        book,
        ["account", "add", "--number", "118", "--name", "Alma Peterson", "--joined", "1994-03-01"],
    )
    run(
        book,
        [
            "account",
            "parcel",
            "--parcel",
            "11-042-001",
            "--account",
            "118",
            "--turnout",
            "L2-14",
            "--acres",
            "40",
        ],
    )
    run(book, ["account", "dry-up", "--parcel", "11-042-001", "--on", "2025-07-01"])
    code, output = run(book, ["account", "dry-up", "--parcel", "11-042-001", "--on", "2025-08-01"])
    assert code != 0
    assert "already dry" in output
