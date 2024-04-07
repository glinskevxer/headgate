import sqlite3
from datetime import date
from decimal import Decimal

import pytest

from headgate.errors import NotFoundError
from headgate.ids import DecreeNumber, DitchCode
from headgate.model.right import Priority, RightKind, RightStatus, WaterRight
from headgate.store.repo_rights import (
    load_active_ladder,
    load_ladder,
    load_right,
    rights_on_ditch,
    rights_senior_to,
    save_right,
    set_status,
)


def right(
    number: str,
    year: int,
    sequence: int = 1,
    kind: RightKind = RightKind.DIRECT_FLOW,
    rate: str | None = "4.5",
    volume: str | None = None,
    status: RightStatus = RightStatus.DECREED,
    ditch: str | None = None,
) -> WaterRight:
    return WaterRight(
        decree=DecreeNumber(number),
        owner="Sanpete Ditch Company",
        kind=kind,
        priority=Priority(date(year, 5, 1), 1889, sequence),
        diversion_mile=Decimal("28.4"),
        rate_cfs=Decimal(rate) if rate is not None else None,
        volume_af=Decimal(volume) if volume is not None else None,
        ditch=DitchCode(ditch) if ditch is not None else None,
        status=status,
    )


def test_a_decree_comes_back_the_way_it_went_in(book: sqlite3.Connection) -> None:
    save_right(book, right("CDA-1889-1", 1873))
    assert load_right(book, DecreeNumber("CDA-1889-1")) == right("CDA-1889-1", 1873)


def test_a_storage_right_keeps_its_volume_and_no_rate(book: sqlite3.Connection) -> None:
    stored = right("CDA-1889-9", 1889, kind=RightKind.STORAGE, rate=None, volume="1200")
    save_right(book, stored)
    loaded = load_right(book, DecreeNumber("CDA-1889-9"))
    assert loaded.rate_cfs is None
    assert loaded.volume_af == Decimal("1200")


def test_saving_a_decree_twice_updates_it(book: sqlite3.Connection) -> None:
    save_right(book, right("CDA-1889-1", 1873))
    save_right(book, right("CDA-1889-1", 1873, rate="6.0"))
    assert load_right(book, DecreeNumber("CDA-1889-1")).rate_cfs == Decimal("6.0")


def test_a_decree_that_is_not_there_is_reported_missing(book: sqlite3.Connection) -> None:
    with pytest.raises(NotFoundError, match="no decree"):
        load_right(book, DecreeNumber("CDA-1889-4"))


def test_the_ladder_comes_back_most_senior_first(book: sqlite3.Connection) -> None:
    save_right(book, right("CDA-1889-9", 1889, 9))
    save_right(book, right("CDA-1889-1", 1873, 1))
    save_right(book, right("CDA-1889-4", 1882, 4))
    assert [item.decree.sequence for item in load_ladder(book)] == [1, 4, 9]


def test_a_tie_on_the_date_is_broken_by_the_sequence(book: sqlite3.Connection) -> None:
    save_right(book, right("CDA-1889-7", 1889, 7))
    save_right(book, right("CDA-1889-3", 1889, 3))
    assert [item.decree.sequence for item in load_ladder(book)] == [3, 7]


def test_an_abandoned_decree_is_left_off_the_active_ladder(book: sqlite3.Connection) -> None:
    save_right(book, right("CDA-1889-1", 1873))
    save_right(book, right("CDA-1889-2", 1875, 2, status=RightStatus.ABANDONED))
    assert len(load_ladder(book)) == 2
    assert len(load_active_ladder(book)) == 1


def test_rights_on_a_ditch_are_listed(book: sqlite3.Connection) -> None:
    book.execute(
        "INSERT INTO ditch (code, name, capacity_cfs, length_feet, loss_per_mile, diversion_mile)"
        " VALUES ('MAIN', 'Sanpete Main Canal', '48', '26400', '0.02', '28.4')"
    )
    save_right(book, right("CDA-1889-1", 1873, ditch="MAIN"))
    save_right(book, right("CDA-1889-2", 1875, 2))
    assert [item.decree.sequence for item in rights_on_ditch(book, DitchCode("MAIN"))] == [1]


def test_rights_senior_to_a_date_are_listed(book: sqlite3.Connection) -> None:
    save_right(book, right("CDA-1889-1", 1873))
    save_right(book, right("CDA-1889-4", 1882, 4))
    senior = rights_senior_to(book, date(1880, 1, 1))
    assert [item.decree.sequence for item in senior] == [1]


def test_a_decree_can_be_marked_abandoned(book: sqlite3.Connection) -> None:
    save_right(book, right("CDA-1889-1", 1873))
    changed = set_status(book, DecreeNumber("CDA-1889-1"), RightStatus.ABANDONED)
    assert changed.status is RightStatus.ABANDONED
    assert not changed.is_active


def test_marking_a_decree_that_is_not_there_is_refused(book: sqlite3.Connection) -> None:
    with pytest.raises(NotFoundError):
        set_status(book, DecreeNumber("CDA-1889-8"), RightStatus.ABANDONED)


def test_the_book_refuses_a_right_with_neither_rate_nor_volume(book: sqlite3.Connection) -> None:
    with pytest.raises(sqlite3.IntegrityError):
        book.execute(
            "INSERT INTO water_right (decree, owner, kind, appropriation_date,"
            " adjudication_year, sequence_number, diversion_mile, status)"
            " VALUES ('CDA-1889-6', 'Nobody', 'direct_flow', '1873-05-01', 1889, 6, '28.4',"
            " 'decreed')"
        )
