from datetime import date
from pathlib import Path

import pytest

from headgate.cli.gages import days_between, next_day
from headgate.errors import ValidationError
from tests.support.district import init_book, lateral, run, stock


@pytest.fixture
def district(tmp_path: Path) -> Path:
    book = stock(init_book(tmp_path / "district.sqlite3"), lateral())
    run(
        book,
        [
            "gage",
            "add",
            "--code",
            "sanp-1",
            "--name",
            "Below the forks",
            "--mile",
            "22",
            "--datum",
            "5412.30",
        ],
    )
    return book


def record(district: Path, day: str, mean: str, grade: str = "measured") -> tuple[int, str]:
    return run(
        district,
        ["gage", "record", "--code", "SANP-1", "--on", day, "--mean", mean, "--grade", grade],
    )


def csv_file(tmp_path: Path, body: str, header: str = "day,mean,grade") -> Path:
    path = tmp_path / "gage.csv"
    path.write_text(f"{header}\n{body}", encoding="utf-8")
    return path


def test_a_gage_is_added_and_listed(district: Path) -> None:
    code, output = run(district, ["gage", "list"])
    assert code == 0
    assert "SANP-1" in output
    assert "Below the forks" in output


def test_a_day_is_recorded(district: Path) -> None:
    code, output = record(district, "2025-06-01", "18.4")
    assert code == 0
    assert "18.400 cfs, measured" in output


def test_a_day_against_a_gage_that_is_not_there_is_refused(district: Path) -> None:
    code, output = run(
        district,
        ["gage", "record", "--code", "SANP-9", "--on", "2025-06-01", "--mean", "18.4"],
    )
    assert code != 0
    assert "no gage" in output


def test_a_negative_flow_is_refused(district: Path) -> None:
    code, output = record(district, "2025-06-01", "-1")
    assert code != 0
    assert "the gage read" in output


def test_a_full_span_reports_its_volume(district: Path) -> None:
    for day, mean in (("2025-06-01", "20"), ("2025-06-02", "18"), ("2025-06-03", "16")):
        record(district, day, mean)
    code, output = run(
        district,
        ["gage", "show", "--code", "SANP-1", "--from", "2025-06-01", "--to", "2025-06-04"],
    )
    assert code == 0
    assert "coverage" in output
    assert "volume" in output
    assert "peak" in output


def test_a_span_with_holes_names_them_instead_of_totalling(district: Path) -> None:
    record(district, "2025-06-01", "20")
    record(district, "2025-06-04", "16")
    code, output = run(
        district,
        ["gage", "show", "--code", "SANP-1", "--from", "2025-06-01", "--to", "2025-06-05"],
    )
    assert code == 0
    assert "days missing, first 2025-06-02" in output
    assert "volume" not in output


def test_an_ice_affected_span_is_not_proved(district: Path) -> None:
    record(district, "2025-06-01", "4.2", "ice-affected")
    code, output = run(
        district,
        ["gage", "show", "--code", "SANP-1", "--from", "2025-06-01", "--to", "2025-06-02"],
    )
    assert code == 0
    assert "proved     no" in output


def test_a_published_record_loads(district: Path, tmp_path: Path) -> None:
    path = csv_file(
        tmp_path, "2025-06-01,20,measured\n2025-06-02,18,measured\n2025-06-03,16,estimated\n"
    )
    code, output = run(district, ["gage", "import", "--code", "SANP-1", str(path)])
    assert code == 0
    assert "3 days loaded" in output


def test_a_record_with_a_bad_flow_loads_nothing(district: Path, tmp_path: Path) -> None:
    path = csv_file(tmp_path, "2025-06-01,20,measured\n2025-06-02,high,measured\n")
    code, output = run(district, ["gage", "import", "--code", "SANP-1", str(path)])
    assert code != 0
    assert "line 3" in output
    code, output = run(district, ["gage", "list"])
    assert " 0" in output


def test_a_record_with_no_day_column_is_refused(district: Path, tmp_path: Path) -> None:
    path = csv_file(tmp_path, "20\n", header="mean")
    code, output = run(district, ["gage", "import", "--code", "SANP-1", str(path)])
    assert code != 0
    assert "no day column" in output


def test_a_record_with_no_days_is_refused(district: Path, tmp_path: Path) -> None:
    path = csv_file(tmp_path, "")
    code, output = run(district, ["gage", "import", "--code", "SANP-1", str(path)])
    assert code != 0
    assert "header and no days" in output


def test_an_empty_book_lists_no_gages(tmp_path: Path) -> None:
    book = stock(init_book(tmp_path / "empty.sqlite3"), lateral())
    code, output = run(book, ["gage", "list"])
    assert code == 0
    assert "no gages yet" in output


def test_the_span_helpers_count_days() -> None:
    assert days_between(date(2025, 6, 1), date(2025, 6, 4)) == 3
    assert next_day(date(2025, 6, 1)) == date(2025, 6, 2)
    with pytest.raises(ValidationError, match="end after it starts"):
        days_between(date(2025, 6, 4), date(2025, 6, 1))
