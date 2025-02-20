from pathlib import Path

import pytest

from tests.support.district import init_book, lateral, run, shareholders, stock


@pytest.fixture
def district(tmp_path: Path) -> Path:
    return stock(init_book(tmp_path / "district.sqlite3"), lateral(), shareholders("30", "10"))


def offer(
    district: Path, number: str = "L-2025-3", volume: str = "80", holding: str = "200"
) -> tuple[int, str]:
    return run(
        district,
        [
            "lease",
            "offer",
            "--number",
            number,
            "--year",
            "2025",
            "--from",
            "118",
            "--to",
            "212",
            "--volume",
            volume,
            "--price",
            "18.00",
            "--holding",
            holding,
            "--on",
            "2025-05-01",
        ],
    )


def test_a_lease_is_offered(district: Path) -> None:
    code, output = offer(district)
    assert code == 0
    assert "80.00 acre feet at $18.00" in output
    assert "120.00 left uncommitted" in output


def test_a_lease_between_accounts_that_are_not_there_is_refused(district: Path) -> None:
    code, output = run(
        district,
        [
            "lease",
            "offer",
            "--number",
            "L-2025-9",
            "--year",
            "2025",
            "--from",
            "999",
            "--to",
            "212",
            "--volume",
            "10",
            "--price",
            "18.00",
            "--holding",
            "200",
        ],
    )
    assert code != 0
    assert "no account" in output


def test_more_water_than_the_lessor_has_is_refused(district: Path) -> None:
    code, output = offer(district, volume="300")
    assert code != 0
    assert "uncommitted" in output


def test_water_already_leased_out_cannot_be_leased_again(district: Path) -> None:
    offer(district, "L-2025-3", "150")
    run(district, ["lease", "approve", "L-2025-3"])
    code, output = offer(district, "L-2025-4", "100")
    assert code != 0
    assert "uncommitted" in output


def test_an_approved_lease_can_deliver(district: Path) -> None:
    offer(district)
    assert run(district, ["lease", "approve", "L-2025-3"])[0] == 0
    code, output = run(district, ["lease", "deliver", "L-2025-3", "--volume", "30"])
    assert code == 0
    assert "delivered 30.00 of 80.00" in output


def test_an_offered_lease_cannot_deliver(district: Path) -> None:
    offer(district)
    code, output = run(district, ["lease", "deliver", "L-2025-3", "--volume", "30"])
    assert code != 0
    assert "cannot deliver water" in output


def test_delivering_the_whole_lease_finishes_it(district: Path) -> None:
    offer(district)
    run(district, ["lease", "approve", "L-2025-3"])
    code, output = run(district, ["lease", "deliver", "L-2025-3", "--volume", "80"])
    assert code == 0
    assert "completed" in output


def test_a_lease_that_has_delivered_cannot_be_cancelled(district: Path) -> None:
    offer(district)
    run(district, ["lease", "approve", "L-2025-3"])
    run(district, ["lease", "deliver", "L-2025-3", "--volume", "10"])
    code, output = run(district, ["lease", "cancel", "L-2025-3", "--note", "too late"])
    assert code != 0
    assert "already delivered" in output


def test_a_lease_can_be_cancelled_before_it_runs(district: Path) -> None:
    offer(district)
    code, output = run(district, ["lease", "cancel", "L-2025-3", "--note", "the lessee sold up"])
    assert code == 0
    assert "cancelled" in output


def test_the_lease_book_lists_a_year(district: Path) -> None:
    offer(district)
    code, output = run(district, ["lease", "list", "--year", "2025"])
    assert code == 0
    assert "L-2025-3" in output
    assert "offered" in output


def test_one_account_sees_its_net_position(district: Path) -> None:
    offer(district)
    run(district, ["lease", "approve", "L-2025-3"])
    code, output = run(district, ["lease", "list", "--year", "2025", "--account", "118"])
    assert code == 0
    assert "-80.00 acre feet in 2025" in output


def test_a_year_with_no_leases_says_so(district: Path) -> None:
    code, output = run(district, ["lease", "list", "--year", "2024"])
    assert code == 0
    assert "no leases in 2024" in output
