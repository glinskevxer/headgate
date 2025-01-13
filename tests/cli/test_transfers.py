from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from headgate.ids import DecreeNumber
from headgate.model.right import Priority, RightKind, WaterRight
from headgate.store.db import Database
from headgate.store.repo_rights import save_right
from tests.support.district import init_book, lateral, run, stock

DECREE = DecreeNumber("CDA-1920-4")


@pytest.fixture
def district(tmp_path: Path) -> Path:
    book = stock(init_book(tmp_path / "district.sqlite3"), lateral())
    with Database(book).open() as connection:
        save_right(
            connection,
            WaterRight(
                decree=DECREE,
                owner="Alma Peterson",
                kind=RightKind.DIRECT_FLOW,
                priority=Priority(date(1889, 5, 1), 1920, 4),
                diversion_mile=Decimal("28.4"),
                rate_cfs=Decimal("4"),
            ),
        )
    return book


def file_one(district: Path, number: str = "T-2025-04", requested: str = "60") -> tuple[int, str]:
    return run(
        district,
        [
            "transfer",
            "file",
            "--number",
            number,
            "--decree",
            "CDA-1920-4",
            "--kind",
            "place-of-use",
            "--filed",
            "2025-02-10",
            "--requested",
            requested,
            "--proved",
            "120",
            "--dry-up",
            "11-042-001",
        ],
    )


def test_an_application_is_filed(district: Path) -> None:
    code, output = file_one(district)
    assert code == 0
    assert "T-2025-04 filed to move 60.00 acre feet" in output


def test_more_than_the_study_proves_cannot_be_filed(district: Path) -> None:
    code, output = file_one(district, requested="400")
    assert code != 0
    assert "the study proves" in output


def test_a_place_of_use_change_needs_ground_to_dry_up(district: Path) -> None:
    code, output = run(
        district,
        [
            "transfer",
            "file",
            "--number",
            "T-2025-05",
            "--decree",
            "CDA-1920-4",
            "--kind",
            "place-of-use",
            "--filed",
            "2025-02-10",
            "--requested",
            "60",
            "--proved",
            "120",
        ],
    )
    assert code != 0
    assert "dries up no ground" in output


def test_filing_the_same_number_twice_is_refused(district: Path) -> None:
    file_one(district)
    code, output = file_one(district)
    assert code != 0
    assert "already been filed" in output


def test_an_application_runs_to_approval(district: Path) -> None:
    file_one(district)
    assert run(district, ["transfer", "publish", "T-2025-04"])[0] == 0
    code, output = run(
        district,
        [
            "transfer",
            "approve",
            "T-2025-04",
            "--approved",
            "50",
            "--consumed-share",
            "0.5",
            "--condition",
            "measure the new headgate weekly",
        ],
    )
    assert code == 0
    assert "50.00 acre feet" in output
    assert "return flow" in output
    assert "11-042-001" in output


def test_an_unpublished_application_cannot_be_approved(district: Path) -> None:
    file_one(district)
    code, output = run(
        district,
        ["transfer", "approve", "T-2025-04", "--approved", "50", "--consumed-share", "0.5"],
    )
    assert code != 0
    assert "cannot be approved yet" in output


def test_terms_over_what_was_asked_for_are_refused(district: Path) -> None:
    file_one(district)
    run(district, ["transfer", "publish", "T-2025-04"])
    code, output = run(
        district,
        ["transfer", "approve", "T-2025-04", "--approved", "90", "--consumed-share", "0.5"],
    )
    assert code != 0
    assert "the terms grant" in output


def test_a_protest_is_recorded_and_can_still_be_approved(district: Path) -> None:
    file_one(district)
    run(district, ["transfer", "publish", "T-2025-04"])
    code, output = run(
        district,
        ["transfer", "protest", "T-2025-04", "--note", "the ditch below will go dry"],
    )
    assert code == 0
    assert "protested" in output
    assert (
        run(
            district,
            ["transfer", "approve", "T-2025-04", "--approved", "40", "--consumed-share", "0.5"],
        )[0]
        == 0
    )


def test_an_application_can_be_denied(district: Path) -> None:
    file_one(district)
    code, output = run(district, ["transfer", "deny", "T-2025-04", "--reason", "no water to move"])
    assert code == 0
    assert "denied: no water to move" in output


def test_the_open_applications_are_listed(district: Path) -> None:
    file_one(district)
    file_one(district, "T-2025-09", "20")
    run(district, ["transfer", "deny", "T-2025-09", "--reason", "withdrawn by the applicant"])
    code, output = run(district, ["transfer", "list", "--open"])
    assert code == 0
    assert "T-2025-04" in output
    assert "T-2025-09" not in output


def test_the_applications_on_a_right_show_what_has_moved(district: Path) -> None:
    file_one(district)
    run(district, ["transfer", "publish", "T-2025-04"])
    run(
        district,
        ["transfer", "approve", "T-2025-04", "--approved", "50", "--consumed-share", "0.5"],
    )
    code, output = run(district, ["transfer", "list", "--decree", "CDA-1920-4"])
    assert code == 0
    assert "50.00 acre feet already moved" in output


def test_an_empty_book_lists_no_applications(district: Path) -> None:
    code, output = run(district, ["transfer", "list"])
    assert code == 0
    assert "no applications" in output
