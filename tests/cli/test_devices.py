from decimal import Decimal
from pathlib import Path

import pytest
from click.testing import CliRunner

from headgate.cli.main import main
from headgate.ids import DitchCode, TurnoutCode
from headgate.model.ditch import Ditch, DitchSystem, Turnout
from headgate.store.db import Database
from headgate.store.repo_ditch import save_system

TURNOUT = TurnoutCode("L2-14")


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
    return path


def run(book: Path, arguments: list[str]) -> tuple[int, str]:
    result = CliRunner().invoke(main, ["--book", str(book), *arguments])
    return result.exit_code, result.output


def install_weir(book: Path) -> tuple[int, str]:
    return run(
        book,
        [
            "device",
            "install",
            "--tag",
            "WEIR-L2-14",
            "--kind",
            "cipolletti-weir",
            "--installed",
            "2016-03-01",
            "--turnout",
            "L2-14",
            "--crest",
            "3",
        ],
    )


def test_a_weir_is_installed_in_a_turnout(book: Path) -> None:
    code, output = install_weir(book)
    assert code == 0
    assert "cipolletti_weir WEIR-L2-14 installed at L2-14" in output


def test_a_weir_without_a_crest_is_refused(book: Path) -> None:
    code, output = run(
        book,
        [
            "device",
            "install",
            "--tag",
            "WEIR-L2-14",
            "--kind",
            "cipolletti-weir",
            "--installed",
            "2016-03-01",
            "--turnout",
            "L2-14",
        ],
    )
    assert code != 0
    assert "no crest width" in output


def test_a_device_that_sits_nowhere_is_refused(book: Path) -> None:
    code, output = run(
        book,
        [
            "device",
            "install",
            "--tag",
            "WEIR-L2-14",
            "--kind",
            "cipolletti-weir",
            "--installed",
            "2016-03-01",
            "--crest",
            "3",
        ],
    )
    assert code != 0
    assert "not installed anywhere" in output


def test_an_unknown_kind_is_refused(book: Path) -> None:
    code, output = run(
        book,
        [
            "device",
            "install",
            "--tag",
            "WEIR-L2-14",
            "--kind",
            "divining-rod",
            "--installed",
            "2016-03-01",
            "--turnout",
            "L2-14",
        ],
    )
    assert code != 0
    assert "divining-rod" in output


def test_a_calibration_stands_for_a_year_by_default(book: Path) -> None:
    install_weir(book)
    code, output = run(
        book,
        [
            "device",
            "calibrate",
            "--tag",
            "WEIR-L2-14",
            "--on",
            "2025-04-01",
            "--by",
            "R. Aldrich",
            "--offset",
            "0.02",
        ],
    )
    assert code == 0
    assert "calibrated 2025-04-01" in output
    assert "2026" in output


def test_a_calibration_that_expires_at_once_is_refused(book: Path) -> None:
    install_weir(book)
    code, output = run(
        book,
        [
            "device",
            "calibrate",
            "--tag",
            "WEIR-L2-14",
            "--on",
            "2025-04-01",
            "--by",
            "R. Aldrich",
            "--months",
            "0",
        ],
    )
    assert code != 0
    assert "proves nothing" in output


def test_calibrating_a_device_that_is_not_there_is_refused(book: Path) -> None:
    code, output = run(
        book,
        ["device", "calibrate", "--tag", "WEIR-L2-20", "--on", "2025-04-01", "--by", "R. Aldrich"],
    )
    assert code != 0
    assert "no device" in output


def test_the_device_list_says_whether_the_check_stands(book: Path) -> None:
    install_weir(book)
    run(
        book,
        [
            "device",
            "calibrate",
            "--tag",
            "WEIR-L2-14",
            "--on",
            "2025-04-01",
            "--by",
            "R. Aldrich",
            "--offset",
            "0.02",
        ],
    )
    code, output = run(book, ["device", "list", "--on", "2025-06-01"])
    assert code == 0
    assert "WEIR-L2-14" in output
    assert "0.020" in output


def test_a_lapsed_check_shows_in_the_list(book: Path) -> None:
    install_weir(book)
    run(
        book,
        ["device", "calibrate", "--tag", "WEIR-L2-14", "--on", "2023-04-01", "--by", "R. Aldrich"],
    )
    code, output = run(book, ["device", "lapsed", "--on", "2025-06-01"])
    assert code == 0
    assert "no calibration standing" in output


def test_a_calibrated_district_reports_nothing_lapsed(book: Path) -> None:
    install_weir(book)
    run(
        book,
        ["device", "calibrate", "--tag", "WEIR-L2-14", "--on", "2025-04-01", "--by", "R. Aldrich"],
    )
    code, output = run(book, ["device", "lapsed", "--on", "2025-06-01"])
    assert code == 0
    assert "every device in the ditch was calibrated" in output


def test_an_empty_book_lists_no_devices(book: Path) -> None:
    code, output = run(book, ["device", "list"])
    assert code == 0
    assert "nothing installed yet" in output


def test_showing_a_device_names_its_rating(book: Path) -> None:
    install_weir(book)
    code, output = run(book, ["device", "show", "WEIR-L2-14", "--on", "2025-06-01"])
    assert code == 0
    assert "Cipolletti" in output
    assert "checks" in output


def test_showing_a_meter_leaves_the_rating_off(book: Path) -> None:
    run(
        book,
        [
            "device",
            "install",
            "--tag",
            "METER-L2-14",
            "--kind",
            "propeller-meter",
            "--installed",
            "2016-03-01",
            "--turnout",
            "L2-14",
        ],
    )
    code, output = run(book, ["device", "show", "METER-L2-14", "--on", "2025-06-01"])
    assert code == 0
    assert "rating" not in output
