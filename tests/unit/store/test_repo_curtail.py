import sqlite3
from datetime import date, datetime
from decimal import Decimal

import pytest

from headgate.errors import ConflictError
from headgate.ids import DecreeNumber
from headgate.model.right import Priority, RightKind, WaterRight
from headgate.priority.curtail import CurtailmentNotice
from headgate.store.repo_curtail import (
    lift_call,
    lift_notice,
    load_register,
    serve_notice,
    standing_at,
)
from headgate.store.repo_rights import save_right

SENIOR = DecreeNumber("CDA-1920-1")
JUNIOR = DecreeNumber("CDA-1920-5")
ISSUED = datetime(2025, 7, 1, 8)
EFFECTIVE = datetime(2025, 7, 2, 8)
LATER = datetime(2025, 7, 10, 8)


def right(decree: DecreeNumber, sequence: int, year: int) -> WaterRight:
    return WaterRight(
        decree=decree,
        owner=f"Owner {sequence}",
        kind=RightKind.DIRECT_FLOW,
        priority=Priority(date(year, 5, 1), 1920, sequence),
        diversion_mile=Decimal("20"),
        rate_cfs=Decimal("4"),
    )


def stocked(book: sqlite3.Connection) -> None:
    save_right(book, right(SENIOR, 1, 1873))
    save_right(book, right(JUNIOR, 5, 1901))


def notice(**overrides: object) -> CurtailmentNotice:
    fields: dict[str, object] = {
        "decree": JUNIOR,
        "called_by": SENIOR,
        "issued_at": ISSUED,
        "effective_at": EFFECTIVE,
        "curtailed_cfs": Decimal("4"),
        "allowed_cfs": Decimal("0"),
        "reason": "call by CDA-1920-1",
    }
    fields.update(overrides)
    return CurtailmentNotice(**fields)  # type: ignore[arg-type]


def test_a_notice_comes_back_the_way_it_went_in(book: sqlite3.Connection) -> None:
    stocked(book)
    serve_notice(book, notice())
    assert load_register(book).notices == (notice(),)


def test_the_same_notice_twice_is_a_conflict(book: sqlite3.Connection) -> None:
    stocked(book)
    serve_notice(book, notice())
    with pytest.raises(ConflictError, match="already"):
        serve_notice(book, notice())


def test_a_notice_against_a_decree_that_is_not_there_is_refused(
    book: sqlite3.Connection,
) -> None:
    with pytest.raises(sqlite3.IntegrityError):
        serve_notice(book, notice())


def test_a_notice_stands_from_when_it_takes_effect(book: sqlite3.Connection) -> None:
    stocked(book)
    serve_notice(book, notice())
    assert standing_at(book, ISSUED) == ()
    assert len(standing_at(book, EFFECTIVE)) == 1


def test_lifting_a_notice_takes_it_out_of_the_standing_list(
    book: sqlite3.Connection,
) -> None:
    stocked(book)
    serve_notice(book, notice())
    assert lift_notice(book, JUNIOR, SENIOR, ISSUED, LATER)
    assert standing_at(book, LATER) == ()
    assert len(standing_at(book, datetime(2025, 7, 4, 8))) == 1


def test_lifting_a_notice_that_is_not_standing_says_so(book: sqlite3.Connection) -> None:
    stocked(book)
    assert not lift_notice(book, JUNIOR, SENIOR, ISSUED, LATER)


def test_lifting_the_same_notice_twice_changes_nothing(book: sqlite3.Connection) -> None:
    stocked(book)
    serve_notice(book, notice())
    assert lift_notice(book, JUNIOR, SENIOR, ISSUED, LATER)
    assert not lift_notice(book, JUNIOR, SENIOR, ISSUED, LATER)


def test_a_whole_call_can_be_lifted_at_once(book: sqlite3.Connection) -> None:
    stocked(book)
    save_right(book, right(DecreeNumber("CDA-1920-6"), 6, 1905))
    serve_notice(book, notice())
    serve_notice(book, notice(decree=DecreeNumber("CDA-1920-6")))
    assert lift_call(book, SENIOR, LATER) == 2
    assert standing_at(book, LATER) == ()


def test_lifting_a_call_nobody_was_served_for_changes_nothing(
    book: sqlite3.Connection,
) -> None:
    stocked(book)
    assert lift_call(book, SENIOR, LATER) == 0


def test_the_register_answers_the_allowed_rate(book: sqlite3.Connection) -> None:
    stocked(book)
    serve_notice(book, notice(allowed_cfs=Decimal("1.5")))
    register = load_register(book)
    assert register.allowed_rate(JUNIOR, EFFECTIVE) == Decimal("1.5")
    assert register.allowed_rate(SENIOR, EFFECTIVE) is None


def test_a_lifted_notice_still_reads_back_with_its_date(book: sqlite3.Connection) -> None:
    stocked(book)
    serve_notice(book, notice())
    lift_notice(book, JUNIOR, SENIOR, ISSUED, LATER)
    assert load_register(book).notices[0].lifted_at == LATER
