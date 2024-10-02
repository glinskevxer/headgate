from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
from click.testing import CliRunner

from headgate.cli.main import main
from headgate.cli.readings import read_rows
from headgate.errors import PolicyError, ValidationError
from headgate.ids import DeviceTag, DitchCode, TurnoutCode
from headgate.model.device import Calibration, Device, DeviceKind
from headgate.model.ditch import Ditch, DitchSystem, Turnout
from headgate.store.db import Database
from headgate.store.repo_devices import save_device
from headgate.store.repo_ditch import save_system

TURNOUT = TurnoutCode("L2-14")
WEIR = DeviceTag("WEIR-L2-14")


@pytest.fixture
def book(tmp_path: Path) -> Path:
    path = tmp_path / "district.sqlite3"
    CliRunner().invoke(
        main,
        [
            "--book",
            str(path),
            "init",
            "--name",
            "Sanpete",
            "--state",
            "ut",
            "--stream",
            "Sanpete Creek",
        ],
    )
    with Database(path).open() as connection:
        save_system(
            connection,
            DitchSystem(
                ditches=(
                    Ditch(
                        code=DitchCode("L2"),
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
        save_device(
            connection,
            Device(
                tag=WEIR,
                kind=DeviceKind.CIPOLLETTI_WEIR,
                installed=date(2016, 3, 1),
                crest_width_feet=Decimal("3"),
                turnout=TURNOUT,
                calibrations=(Calibration(date(2025, 4, 1), "R. Aldrich", date(2026, 4, 1)),),
            ),
        )
    return path


def run(book: Path, arguments: list[str]) -> tuple[int, str]:
    result = CliRunner().invoke(main, ["--book", str(book), *arguments])
    return result.exit_code, result.output


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
    assert "checks out" in output
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
