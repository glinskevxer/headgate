"""A rationed year: an allotment, a lease, and the reservoir making up the rest.

The pieces are separately tested. What matters here is that they agree about
one shareholder's water: the allotment says what he may take, the lease moves
some of it to somebody else, the reservoir hands him stored water that is not
part of the allotment at all, and the order intake reads the allotment back
when it answers him.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from headgate.ids import AccountNumber, DecreeNumber
from headgate.model.right import Priority, RightKind, WaterRight
from headgate.store.db import Database
from headgate.store.repo_allotment import load_ledger
from headgate.store.repo_leases import load_book, net_leased
from headgate.store.repo_rights import save_right
from headgate.store.repo_season import declare_season
from headgate.store.repo_storage import load_storage_book
from headgate.wateryear import IrrigationSeason
from tests.support.district import (
    HOLDER,
    SECOND_HOLDER,
    cipolletti,
    init_book,
    lateral,
    must,
    run,
    shareholders,
    stock,
)

STORAGE = DecreeNumber("CDA-1920-40")


@pytest.fixture
def district(tmp_path: Path) -> Path:
    book = stock(
        init_book(tmp_path / "district.sqlite3"),
        lateral(),
        shareholders("30", "10"),
        devices=(cipolletti(),),
    )
    with Database(book).open() as connection:
        declare_season(connection, IrrigationSeason.default_for(2025), date(2025, 3, 20))
        save_right(
            connection,
            WaterRight(
                decree=STORAGE,
                owner="Sanpete Ditch Company",
                kind=RightKind.STORAGE,
                priority=Priority(date(1911, 5, 1), 1920, 40),
                diversion_mile=Decimal("31"),
                volume_af=Decimal("4000"),
            ),
        )
    must(
        book,
        [
            "allotment",
            "set",
            "--year",
            "2025",
            "--available",
            "800",
            "--basis",
            "April forecast at 70 percent",
            "--on",
            "2025-04-01",
        ],
    )
    return book


def test_the_allotment_follows_the_shares(district: Path) -> None:
    with Database(district).open() as connection:
        ledger = load_ledger(connection, 2025)
    assert ledger.allowed_af(HOLDER) == Decimal("600")
    assert ledger.allowed_af(SECOND_HOLDER) == Decimal("200")


def test_an_order_is_cut_to_what_is_left_of_the_allotment(district: Path) -> None:
    must(district, ["allotment", "take", "--year", "2025", "--account", "118", "--volume", "590"])
    must(
        district,
        [
            "order",
            "place",
            "--account",
            "118",
            "--turnout",
            "L2-14",
            "--rate",
            "5",
            "--from",
            "2025-07-01T06:00",
            "--to",
            "2025-07-08T06:00",
            "--placed",
            "2025-06-28T08:00",
        ],
    )
    answered = must(district, ["order", "answer", "1"])
    assert "reduced" in answered
    assert "allotment left" in answered


def test_an_account_with_nothing_left_is_refused_outright(district: Path) -> None:
    must(district, ["allotment", "take", "--year", "2025", "--account", "118", "--volume", "600"])
    must(
        district,
        [
            "order",
            "place",
            "--account",
            "118",
            "--turnout",
            "L2-14",
            "--rate",
            "2",
            "--from",
            "2025-07-01T06:00",
            "--to",
            "2025-07-08T06:00",
            "--placed",
            "2025-06-28T08:00",
        ],
    )
    answered = must(district, ["order", "answer", "1"])
    assert "refused" in answered


def test_a_lease_moves_water_between_two_shareholders(district: Path) -> None:
    must(
        district,
        [
            "lease",
            "offer",
            "--number",
            "L-2025-1",
            "--year",
            "2025",
            "--from",
            "118",
            "--to",
            "212",
            "--volume",
            "100",
            "--price",
            "18.00",
            "--holding",
            "600",
            "--on",
            "2025-05-01",
        ],
    )
    must(district, ["lease", "approve", "L-2025-1"])
    with Database(district).open() as connection:
        assert net_leased(connection, HOLDER, 2025) == Decimal("-100")
        assert net_leased(connection, SECOND_HOLDER, 2025) == Decimal("100")
        assert len(load_book(connection, 2025).live) == 1


def test_a_shareholder_cannot_lease_out_water_twice(district: Path) -> None:
    must(
        district,
        [
            "lease",
            "offer",
            "--number",
            "L-2025-1",
            "--year",
            "2025",
            "--from",
            "118",
            "--to",
            "212",
            "--volume",
            "500",
            "--price",
            "18.00",
            "--holding",
            "600",
            "--on",
            "2025-05-01",
        ],
    )
    must(district, ["lease", "approve", "L-2025-1"])
    code, output = run(
        district,
        [
            "lease",
            "offer",
            "--number",
            "L-2025-2",
            "--year",
            "2025",
            "--from",
            "118",
            "--to",
            "212",
            "--volume",
            "200",
            "--price",
            "18.00",
            "--holding",
            "600",
            "--on",
            "2025-05-10",
        ],
    )
    assert code != 0
    assert "uncommitted" in output


def test_stored_water_is_a_separate_account_from_the_allotment(district: Path) -> None:
    must(
        district,
        [
            "reservoir",
            "build",
            "--name",
            "Ephraim Reservoir",
            "--decree",
            "CDA-1920-40",
            "--capacity",
            "4000",
            "--dead-pool",
            "300",
        ],
    )
    must(
        district,
        [
            "reservoir",
            "fill",
            "--name",
            "Ephraim Reservoir",
            "--on",
            "2025-04-01",
            "--inflow",
            "1700",
        ],
    )
    must(
        district,
        [
            "reservoir",
            "allocate",
            "--name",
            "Ephraim Reservoir",
            "--year",
            "2025",
            "--on",
            "2025-04-15",
        ],
    )
    must(
        district,
        [
            "reservoir",
            "draw",
            "--name",
            "Ephraim Reservoir",
            "--year",
            "2025",
            "--account",
            "118",
            "--volume",
            "200",
        ],
    )
    with Database(district).open() as connection:
        stored = load_storage_book(connection, "Ephraim Reservoir", 2025)
        allotted = load_ledger(connection, 2025)
    assert stored.balance_of(AccountNumber(118)) == Decimal("1075.0000")
    assert allotted.remaining_af(HOLDER) == Decimal("600")


def test_the_allotment_can_be_cut_when_the_creek_quits(district: Path) -> None:
    must(district, ["allotment", "take", "--year", "2025", "--account", "118", "--volume", "500"])
    must(
        district,
        [
            "allotment",
            "revise",
            "--year",
            "2025",
            "--per-share",
            "12",
            "--on",
            "2025-08-01",
            "--basis",
            "creek quit",
        ],
    )
    output = must(district, ["allotment", "show", "--year", "2025"])
    assert "over their allotment" in output
    with Database(district).open() as connection:
        ledger = load_ledger(connection, 2025)
    assert ledger.is_over(HOLDER)
    assert ledger.over_by(HOLDER) == Decimal("140")


def test_the_log_shows_what_the_office_did_in_the_dry_year(district: Path) -> None:
    must(district, ["allotment", "take", "--year", "2025", "--account", "118", "--volume", "100"])
    output = must(district, ["log"])
    assert "allotment set" in output
    assert "allotment take" in output
