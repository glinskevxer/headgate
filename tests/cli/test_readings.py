from pathlib import Path

import pytest

from headgate.cli.readings import read_rows
from headgate.errors import PolicyError, ValidationError
from tests.support.district import cipolletti, init_book, lateral, run, stock


@pytest.fixture
def book(tmp_path: Path) -> Path:
    return stock(init_book(tmp_path / "district.sqlite3"), lateral(), devices=(cipolletti(),))


def csv_file(tmp_path: Path, body: str, header: str = "device,taken_at,observer,head,note") -> Path:
    path = tmp_path / "readings.csv"
    path.write_text(f"{header}\n{body}", encoding="utf-8")
    return path


def test_a_reading_is_written_and_rated(book: Path) -> None:
    code, output = run(
        book,
        [
            "reading",
            "add",
            "--device",
            "WEIR-L2-14",
            "--at",
            "2025-06-01T06:00",
            "--by",
            "D. Yardley",
            "--head",
            "0.62",
        ],
    )
    assert code == 0
    assert "measured" in output
    assert "cfs" in output


def test_a_reading_past_the_rating_says_it_is_an_estimate(book: Path) -> None:
    code, output = run(
        book,
        [
            "reading",
            "add",
            "--device",
            "WEIR-L2-14",
            "--at",
            "2025-06-01T06:00",
            "--by",
            "D. Yardley",
            "--head",
            "1.40",
        ],
    )
    assert code == 0
    assert "estimated" in output


def test_the_same_instant_twice_is_refused(book: Path) -> None:
    run(
        book,
        [
            "reading",
            "add",
            "--device",
            "WEIR-L2-14",
            "--at",
            "2025-06-01T06:00",
            "--by",
            "D. Yardley",
            "--head",
            "0.62",
        ],
    )
    code, output = run(
        book,
        [
            "reading",
            "add",
            "--device",
            "WEIR-L2-14",
            "--at",
            "2025-06-01T06:00",
            "--by",
            "D. Yardley",
            "--head",
            "0.70",
        ],
    )
    assert code != 0
    assert "already read at" in output


def test_a_reading_for_a_device_that_is_not_there_is_refused(book: Path) -> None:
    code, output = run(
        book,
        [
            "reading",
            "add",
            "--device",
            "WEIR-L2-20",
            "--at",
            "2025-06-01T06:00",
            "--by",
            "D. Yardley",
            "--head",
            "0.62",
        ],
    )
    assert code != 0
    assert "no device" in output


def test_the_readings_on_a_device_are_listed(book: Path) -> None:
    run(
        book,
        [
            "reading",
            "add",
            "--device",
            "WEIR-L2-14",
            "--at",
            "2025-06-01T06:00",
            "--by",
            "D. Yardley",
            "--head",
            "0.62",
            "--note",
            "ran clear",
        ],
    )
    code, output = run(book, ["reading", "list", "WEIR-L2-14"])
    assert code == 0
    assert "2025-06-01 06:00" in output
    assert "ran clear" in output


def test_a_device_nobody_has_read_says_so(book: Path) -> None:
    code, output = run(book, ["reading", "list", "WEIR-L2-14"])
    assert code == 0
    assert "nobody has read" in output


def test_a_file_of_readings_loads(book: Path, tmp_path: Path) -> None:
    path = csv_file(
        tmp_path,
        "WEIR-L2-14,2025-06-01T06:00,D. Yardley,0.62,ran clear\n"
        "WEIR-L2-14,2025-06-04T06:00,D. Yardley,0.58,\n",
    )
    code, output = run(book, ["reading", "import", str(path)])
    assert code == 0
    assert "2 readings loaded" in output


def test_a_dry_run_writes_nothing(book: Path, tmp_path: Path) -> None:
    path = csv_file(tmp_path, "WEIR-L2-14,2025-06-01T06:00,D. Yardley,0.62,\n")
    code, output = run(book, ["reading", "import", str(path), "--dry-run"])
    assert code == 0
    assert "1 readings for 1 device" in output
    code, output = run(book, ["reading", "list", "WEIR-L2-14"])
    assert "nobody has read" in output


def test_a_file_with_a_bad_row_loads_nothing(book: Path, tmp_path: Path) -> None:
    path = csv_file(
        tmp_path,
        "WEIR-L2-14,2025-06-01T06:00,D. Yardley,0.62,\n"
        "WEIR-L2-14,2025-06-04T06:00,D. Yardley,about a foot,\n",
    )
    code, output = run(book, ["reading", "import", str(path)])
    assert code != 0
    assert "line 3" in output
    code, output = run(book, ["reading", "list", "WEIR-L2-14"])
    assert "nobody has read" in output


def test_a_file_naming_a_device_that_is_not_there_loads_nothing(book: Path, tmp_path: Path) -> None:
    path = csv_file(
        tmp_path,
        "WEIR-L2-14,2025-06-01T06:00,D. Yardley,0.62,\n"
        "WEIR-L2-99,2025-06-04T06:00,D. Yardley,0.58,\n",
    )
    code, output = run(book, ["reading", "import", str(path)])
    assert code != 0
    code, output = run(book, ["reading", "list", "WEIR-L2-14"])
    assert "nobody has read" in output


def test_a_file_with_no_readings_is_refused(tmp_path: Path) -> None:
    path = csv_file(tmp_path, "")
    with pytest.raises(PolicyError, match="header and no readings"):
        read_rows(path)


def test_a_file_with_no_device_column_is_refused(tmp_path: Path) -> None:
    path = csv_file(tmp_path, "2025-06-01T06:00,D. Yardley\n", header="taken_at,observer")
    with pytest.raises(ValidationError, match="no device column"):
        read_rows(path)


def test_an_empty_file_is_refused(tmp_path: Path) -> None:
    path = tmp_path / "empty.csv"
    path.write_text("", encoding="utf-8")
    with pytest.raises(ValidationError, match="no header row"):
        read_rows(path)


def logger_file(tmp_path: Path, rows: list[str]) -> Path:
    path = tmp_path / "logger.csv"
    path.write_text("taken_at,head,battery\n" + "\n".join(rows) + "\n", encoding="utf-8")
    return path


def steady_rows(count: int = 48, head: str = "0.60", battery: str = "12.4") -> list[str]:
    from datetime import datetime, timedelta

    start = datetime(2025, 6, 1, 6)
    return [
        f"{(start + timedelta(minutes=15 * index)):%Y-%m-%dT%H:%M},{head},{battery}"
        for index in range(count)
    ]


def test_a_logger_file_is_thinned_into_the_book(book: Path, tmp_path: Path) -> None:
    path = logger_file(tmp_path, steady_rows())
    code, output = run(book, ["reading", "logger", "--device", "WEIR-L2-14", str(path)])
    assert code == 0
    assert "48 samples" in output
    assert "readings written" in output


def test_a_dry_run_of_a_logger_file_writes_nothing(book: Path, tmp_path: Path) -> None:
    path = logger_file(tmp_path, steady_rows())
    code, output = run(
        book, ["reading", "logger", "--device", "WEIR-L2-14", str(path), "--dry-run"]
    )
    assert code == 0
    assert "this was a dry run" in output
    _, listed = run(book, ["reading", "list", "WEIR-L2-14"])
    assert "nobody has read" in listed


def test_a_spike_is_dropped_before_the_book_sees_it(book: Path, tmp_path: Path) -> None:
    rows = steady_rows(4)
    rows.insert(2, "2025-06-01T06:20,3.40,12.4")
    path = logger_file(tmp_path, sorted(rows))
    code, output = run(book, ["reading", "logger", "--device", "WEIR-L2-14", str(path)])
    assert code == 0
    assert "spikes dropped" in output


def test_a_flatlined_sensor_is_reported(book: Path, tmp_path: Path) -> None:
    path = logger_file(tmp_path, steady_rows(count=300))
    code, output = run(
        book, ["reading", "logger", "--device", "WEIR-L2-14", str(path), "--dry-run"]
    )
    assert code == 0
    assert "same number for two days" in output


def test_a_low_battery_is_reported(book: Path, tmp_path: Path) -> None:
    path = logger_file(tmp_path, steady_rows(battery="10.9"))
    code, output = run(
        book, ["reading", "logger", "--device", "WEIR-L2-14", str(path), "--dry-run"]
    )
    assert code == 0
    assert "low battery" in output


def test_a_file_with_no_timestamp_column_is_refused(book: Path, tmp_path: Path) -> None:
    path = tmp_path / "logger.csv"
    path.write_text("head\n0.60\n", encoding="utf-8")
    code, output = run(book, ["reading", "logger", "--device", "WEIR-L2-14", str(path)])
    assert code != 0
    assert "no taken_at column" in output


def test_a_file_with_no_samples_is_refused(book: Path, tmp_path: Path) -> None:
    path = logger_file(tmp_path, [])
    code, output = run(book, ["reading", "logger", "--device", "WEIR-L2-14", str(path)])
    assert code != 0
    assert "header and no samples" in output


def test_loading_the_same_file_twice_writes_nothing_new(book: Path, tmp_path: Path) -> None:
    path = logger_file(tmp_path, steady_rows())
    run(book, ["reading", "logger", "--device", "WEIR-L2-14", str(path)])
    code, output = run(book, ["reading", "logger", "--device", "WEIR-L2-14", str(path)])
    assert code == 0
    assert "0 readings written" in output
