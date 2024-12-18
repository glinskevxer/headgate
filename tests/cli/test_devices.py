from pathlib import Path

import pytest

from tests.support.district import init_book, lateral, run, stock


@pytest.fixture
def book(tmp_path: Path) -> Path:
    return stock(init_book(tmp_path / "district.sqlite3"), lateral())


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
