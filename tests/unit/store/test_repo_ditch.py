import sqlite3
from decimal import Decimal

import pytest

from headgate.errors import StoreError, ValidationError
from headgate.ids import DitchCode, TurnoutCode
from headgate.model.ditch import Ditch, DitchSystem, Turnout
from headgate.model.stream import Reach, Stream
from headgate.store.repo_ditch import (
    load_stream,
    load_system,
    save_stream,
    save_system,
    turnout_codes,
)


def turnout(code: str, station: str) -> Turnout:
    return Turnout(
        code=TurnoutCode(code),
        name=f"{code} headgate",
        station_feet=Decimal(station),
        capacity_cfs=Decimal("3"),
        served_acres=Decimal("40"),
    )


def system() -> DitchSystem:
    main = Ditch(
        code=DitchCode("MAIN"),
        name="Sanpete Main Canal",
        capacity_cfs=Decimal("48"),
        length_feet=Decimal("26400"),
        loss_fraction_per_mile=Decimal("0.02"),
        turnouts=(turnout("MAIN-3", "5280"),),
        diversion_mile=Decimal("28.4"),
    )
    lateral = Ditch(
        code=DitchCode("L2"),
        name="Second Lateral",
        capacity_cfs=Decimal("12"),
        length_feet=Decimal("10560"),
        loss_fraction_per_mile=Decimal("0.04"),
        turnouts=(turnout("L2-14", "5280"), turnout("L2-20", "9000")),
        parent=DitchCode("MAIN"),
        offtake_station_feet=Decimal("15840"),
    )
    return DitchSystem(ditches=(main, lateral))


def stream() -> Stream:
    return Stream(
        name="Sanpete Creek",
        reaches=(
            Reach(
                "R1", "Above the ditch", Decimal("30"), Decimal("22"), Decimal("2"), Decimal("0.01")
            ),
            Reach(
                "R2", "Below the ditch", Decimal("22"), Decimal("14"), Decimal("3"), Decimal("0.02")
            ),
        ),
    )


def test_a_system_comes_back_the_way_it_went_in(book: sqlite3.Connection) -> None:
    save_system(book, system())
    assert load_system(book) == system()


def test_a_lateral_is_written_after_the_parent_it_refers_to(book: sqlite3.Connection) -> None:
    reversed_order = DitchSystem(ditches=tuple(reversed(system().ditches)))
    save_system(book, reversed_order)
    assert load_system(book).main.code == DitchCode("MAIN")


def test_saving_again_replaces_what_was_there(book: sqlite3.Connection) -> None:
    save_system(book, system())
    trimmed = DitchSystem(ditches=(system().main,))
    save_system(book, trimmed)
    assert len(load_system(book).ditches) == 1


def test_turnouts_come_back_on_the_ditch_they_belong_to(book: sqlite3.Connection) -> None:
    save_system(book, system())
    loaded = load_system(book)
    assert len(loaded.ditch(DitchCode("L2")).turnouts) == 2
    assert len(loaded.ditch(DitchCode("MAIN")).turnouts) == 1


def test_decimals_survive_the_trip(book: sqlite3.Connection) -> None:
    save_system(book, system())
    loaded = load_system(book)
    assert loaded.ditch(DitchCode("L2")).loss_fraction_per_mile == Decimal("0.04")


def test_the_turnout_codes_come_back_sorted(book: sqlite3.Connection) -> None:
    save_system(book, system())
    assert turnout_codes(book) == (
        TurnoutCode("L2-14"),
        TurnoutCode("L2-20"),
        TurnoutCode("MAIN-3"),
    )


def test_an_empty_book_has_no_system(book: sqlite3.Connection) -> None:
    with pytest.raises(ValidationError, match="no ditches"):
        load_system(book)


def test_a_stream_comes_back_head_to_toe(book: sqlite3.Connection) -> None:
    save_stream(book, stream())
    assert load_stream(book, "Sanpete Creek") == stream()


def test_saving_a_stream_replaces_the_reaches(book: sqlite3.Connection) -> None:
    save_stream(book, stream())
    one_reach = Stream(name="Sanpete Creek", reaches=(stream().reaches[0],))
    save_stream(book, one_reach)
    assert len(load_stream(book, "Sanpete Creek").reaches) == 1


def test_a_hand_edited_row_is_caught_when_it_is_read(book: sqlite3.Connection) -> None:
    save_system(book, system())
    book.execute("UPDATE ditch SET capacity_cfs = 'plenty' WHERE code = 'L2'")
    with pytest.raises(StoreError, match="ditch.capacity_cfs"):
        load_system(book)
