from pathlib import Path

import pytest

from tests.support.district import init_book, lateral, run, stock


@pytest.fixture
def district(tmp_path: Path) -> Path:
    return stock(init_book(tmp_path / "district.sqlite3"), lateral())


def add_right(district: Path, decree: str = "CDA-1920-4", year: str = "1889") -> tuple[int, str]:
    return run(
        district,
        [
            "right",
            "add",
            "--decree",
            decree,
            "--owner",
            "Alma Peterson",
            "--appropriated",
            f"{year}-05-01",
            "--sequence",
            decree.rsplit("-", 1)[1],
            "--mile",
            "28.4",
            "--rate",
            "4",
        ],
    )


def add_reach(district: Path, code: str, head: str, toe: str) -> tuple[int, str]:
    return run(
        district,
        [
            "stream",
            "reach",
            "--name",
            "Sanpete Creek",
            "--code",
            code,
            "--label",
            f"{code} reach",
            "--head",
            head,
            "--toe",
            toe,
        ],
    )


def test_a_decree_is_written_and_read_back(district: Path) -> None:
    code, output = add_right(district)
    assert code == 0
    assert "CDA-1920-4 decreed to Alma Peterson" in output
    code, output = run(district, ["right", "show", "CDA-1920-4"])
    assert "1889-05-01" in output
    assert "may call" in output


def test_a_decree_with_no_rate_or_volume_is_refused(district: Path) -> None:
    code, output = run(
        district,
        [
            "right",
            "add",
            "--decree",
            "CDA-1920-4",
            "--owner",
            "Alma Peterson",
            "--appropriated",
            "1889-05-01",
            "--sequence",
            "4",
            "--mile",
            "28.4",
        ],
    )
    assert code != 0
    assert "decrees no rate" in output


def test_a_storage_right_takes_a_volume(district: Path) -> None:
    code, output = run(
        district,
        [
            "right",
            "add",
            "--decree",
            "CDA-1920-40",
            "--owner",
            "Sanpete Ditch Company",
            "--kind",
            "storage",
            "--appropriated",
            "1911-05-01",
            "--sequence",
            "40",
            "--mile",
            "31",
            "--volume",
            "4000",
        ],
    )
    assert code == 0
    assert "CDA-1920-40" in output


def test_a_priority_the_adjudication_could_not_confirm_is_refused(district: Path) -> None:
    code, output = add_right(district, year="1930")
    assert code != 0
    assert "cannot confirm" in output


def test_the_ladder_lists_most_senior_first(district: Path) -> None:
    add_right(district, "CDA-1920-9", "1901")
    add_right(district, "CDA-1920-1", "1873")
    code, output = run(district, ["right", "list"])
    assert code == 0
    lines = [line for line in output.splitlines() if line.startswith("CDA")]
    assert lines[0].startswith("CDA-1920-1")


def test_an_abandoned_right_can_be_left_off_the_list(district: Path) -> None:
    add_right(district, "CDA-1920-1", "1873")
    add_right(district, "CDA-1920-9", "1901")
    run(district, ["right", "abandon", "CDA-1920-9"])
    code, output = run(district, ["right", "list", "--active"])
    assert code == 0
    assert "CDA-1920-9" not in output


def test_abandoning_a_right_says_so(district: Path) -> None:
    add_right(district)
    code, output = run(district, ["right", "abandon", "CDA-1920-4"])
    assert code == 0
    assert "is now abandoned" in output


def test_an_empty_book_lists_no_decrees(district: Path) -> None:
    code, output = run(district, ["right", "list"])
    assert code == 0
    assert "no decrees yet" in output


def test_a_reach_is_added_to_the_creek(district: Path) -> None:
    code, output = add_reach(district, "R1", "40", "20")
    assert code == 0
    assert "reach R1 added" in output
    assert "20 miles" in output


def test_reaches_are_kept_head_to_toe(district: Path) -> None:
    add_reach(district, "R2", "20", "4")
    add_reach(district, "R1", "40", "20")
    code, output = run(district, ["stream", "show", "--name", "Sanpete Creek"])
    assert code == 0
    lines = [line for line in output.splitlines() if line.startswith("R")]
    assert lines[0].startswith("R1")
    assert "mile 40 to 4" in output


def test_a_reach_that_leaves_a_gap_is_refused(district: Path) -> None:
    add_reach(district, "R1", "40", "20")
    code, output = add_reach(district, "R2", "18", "4")
    assert code != 0
    assert "leaving a gap" in output


def test_a_creek_with_no_reaches_says_so(district: Path) -> None:
    code, output = run(district, ["stream", "show", "--name", "Sanpete Creek"])
    assert code != 0
