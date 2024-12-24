import sqlite3
from datetime import date
from decimal import Decimal

import pytest

from headgate.duty.hcu import HistoricalUse, YearFinding
from headgate.errors import ConflictError, NotFoundError
from headgate.ids import DecreeNumber, DitchCode, TurnoutCode
from headgate.model.ditch import Ditch, DitchSystem, Turnout
from headgate.model.right import Priority, RightKind, WaterRight
from headgate.store.repo_ditch import save_system
from headgate.store.repo_rights import save_right
from headgate.store.repo_transfers import (
    applications_on,
    approved_volume_on,
    file_application,
    load_application,
    open_applications,
    save_application,
)
from headgate.transfer.application import (
    TransferApplication,
    TransferKind,
    TransferStatus,
    terms_for,
)

DECREE = DecreeNumber("CDA-1920-4")
FROM = TurnoutCode("L2-14")
TO = TurnoutCode("L2-20")


def stocked(book: sqlite3.Connection) -> None:
    save_system(
        book,
        DitchSystem(
            ditches=(
                Ditch(
                    code=DitchCode("L2"),
                    name="Second Lateral",
                    capacity_cfs=Decimal("12"),
                    length_feet=Decimal("10560"),
                    loss_fraction_per_mile=Decimal("0.05"),
                    turnouts=(
                        Turnout(FROM, "Lower gate", Decimal("5280"), Decimal("6"), Decimal("40")),
                        Turnout(TO, "Tail gate", Decimal("9000"), Decimal("4"), Decimal("25")),
                    ),
                    diversion_mile=Decimal("28.4"),
                ),
            )
        ),
    )
    save_right(
        book,
        WaterRight(
            decree=DECREE,
            owner="Alma Peterson",
            kind=RightKind.DIRECT_FLOW,
            priority=Priority(date(1889, 5, 1), 1920, 4),
            diversion_mile=Decimal("28.4"),
            rate_cfs=Decimal("4"),
        ),
    )


def study(average: str = "120") -> HistoricalUse:
    return HistoricalUse(
        findings=(YearFinding(2020, Decimal(average), True, "measured"),),
        average_af=Decimal(average),
    )


def application(number: str = "T-2025-04", requested: str = "60") -> TransferApplication:
    return TransferApplication(
        number=number,
        decree=DECREE,
        kind=TransferKind.BOTH,
        filed_on=date(2025, 2, 10),
        requested_af=Decimal(requested),
        study=study(),
        from_turnout=FROM,
        to_turnout=TO,
        dry_up_parcels=("11-042-001", "11-042-002"),
    )


def test_an_application_comes_back_the_way_it_was_filed(book: sqlite3.Connection) -> None:
    stocked(book)
    file_application(book, application())
    loaded = load_application(book, "T-2025-04")
    assert loaded.requested_af == Decimal("60")
    assert loaded.study.average_af == Decimal("120")
    assert loaded.dry_up_parcels == ("11-042-001", "11-042-002")


def test_filing_the_same_number_twice_is_a_conflict(book: sqlite3.Connection) -> None:
    stocked(book)
    file_application(book, application())
    with pytest.raises(ConflictError, match="already been filed"):
        file_application(book, application())


def test_an_application_against_a_decree_that_is_not_there_is_refused(
    book: sqlite3.Connection,
) -> None:
    with pytest.raises(sqlite3.IntegrityError):
        file_application(book, application())


def test_an_application_that_is_not_there_is_reported_missing(
    book: sqlite3.Connection,
) -> None:
    with pytest.raises(NotFoundError, match="no transfer application"):
        load_application(book, "T-2025-99")


def test_moving_an_application_along_is_written_back(book: sqlite3.Connection) -> None:
    stocked(book)
    file_application(book, application())
    save_application(book, load_application(book, "T-2025-04").publish())
    assert load_application(book, "T-2025-04").status is TransferStatus.PUBLISHED


def test_approval_writes_the_terms(book: sqlite3.Connection) -> None:
    stocked(book)
    file_application(book, application())
    published = load_application(book, "T-2025-04").publish()
    terms = terms_for(
        published, Decimal("50"), Decimal("0.5"), ("measure the new headgate weekly",)
    )
    save_application(book, published.approve(terms))
    loaded = load_application(book, "T-2025-04")
    assert loaded.status is TransferStatus.APPROVED
    assert loaded.terms is not None
    assert loaded.terms.approved_af == Decimal("50")
    assert loaded.terms.return_flow_af == Decimal("50.0000")
    assert loaded.terms.conditions == ("measure the new headgate weekly",)


def test_saving_an_application_that_was_never_filed_is_refused(
    book: sqlite3.Connection,
) -> None:
    stocked(book)
    with pytest.raises(NotFoundError):
        save_application(book, application())


def test_applications_on_a_decree_are_listed(book: sqlite3.Connection) -> None:
    stocked(book)
    file_application(book, application("T-2025-04"))
    file_application(book, application("T-2025-09", requested="20"))
    assert len(applications_on(book, DECREE)) == 2


def test_only_the_ones_still_moving_are_open(book: sqlite3.Connection) -> None:
    stocked(book)
    file_application(book, application("T-2025-04"))
    file_application(book, application("T-2025-09", requested="20"))
    save_application(book, load_application(book, "T-2025-09").deny("no water to move"))
    assert [item.number for item in open_applications(book)] == ["T-2025-04"]


def test_the_volume_already_moved_off_a_right_adds_up(book: sqlite3.Connection) -> None:
    stocked(book)
    file_application(book, application("T-2025-04"))
    published = load_application(book, "T-2025-04").publish()
    save_application(book, published.approve(terms_for(published, Decimal("50"), Decimal("0.5"))))
    assert approved_volume_on(book, DECREE) == Decimal("50")
    assert approved_volume_on(book, DecreeNumber("CDA-1920-9")) == Decimal("0")


def test_a_denied_application_moves_nothing(book: sqlite3.Connection) -> None:
    stocked(book)
    file_application(book, application())
    save_application(book, load_application(book, "T-2025-04").deny("no water to move"))
    assert approved_volume_on(book, DECREE) == Decimal("0")
