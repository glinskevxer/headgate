from datetime import date, datetime
from decimal import Decimal
from enum import Enum

import pytest

from headgate.errors import StoreError
from headgate.ids import TurnoutCode
from headgate.store.serial import (
    code_text,
    date_text,
    decimal_text,
    enum_text,
    flag_int,
    instant_text,
    int_flag,
    int_value,
    lines_text,
    optional_date,
    optional_date_text,
    optional_decimal,
    optional_decimal_text,
    text_date,
    text_decimal,
    text_enum,
    text_instant,
    text_lines,
    text_value,
)


class Colour(Enum):
    RED = "red"
    YELLOW = "yellow"


class Numbered(Enum):
    ONE = 1


def test_a_decimal_stores_and_reads_back_exactly() -> None:
    assert decimal_text(Decimal("1.9835")) == "1.9835"
    assert text_decimal("1.9835") == Decimal("1.9835")


def test_a_stored_decimal_keeps_its_trailing_zeroes() -> None:
    assert decimal_text(Decimal("2.5000")) == "2.5000"


def test_a_column_that_is_not_a_number_is_a_store_error() -> None:
    with pytest.raises(StoreError, match="not a number"):
        text_decimal("about four", "turnout.capacity_cfs")


def test_a_column_holding_the_wrong_type_says_which_column() -> None:
    with pytest.raises(StoreError, match="turnout.capacity_cfs"):
        text_decimal(4.0, "turnout.capacity_cfs")


def test_an_optional_decimal_passes_nothing_through() -> None:
    assert optional_decimal(None) is None
    assert optional_decimal("3") == Decimal("3")


def test_writing_an_optional_decimal_passes_nothing_through() -> None:
    assert optional_decimal_text(None) is None
    assert optional_decimal_text(Decimal("3.50")) == "3.50"


def test_writing_an_optional_date_passes_nothing_through() -> None:
    assert optional_date_text(None) is None
    assert optional_date_text(date(2025, 4, 15)) == "2025-04-15"


def test_writing_an_identifier_uses_the_text_it_prints_as() -> None:
    assert code_text(None) is None
    assert code_text(TurnoutCode("L2-14")) == "L2-14"


def test_dates_round_trip() -> None:
    assert date_text(date(2025, 4, 15)) == "2025-04-15"
    assert text_date("2025-04-15") == date(2025, 4, 15)
    assert optional_date(None) is None


def test_a_column_that_is_not_a_date_is_a_store_error() -> None:
    with pytest.raises(StoreError, match="not a date"):
        text_date("15 April")


def test_timestamps_round_trip_to_the_second() -> None:
    moment = datetime(2025, 6, 1, 6, 30, 15)
    assert instant_text(moment) == "2025-06-01 06:30:15"
    assert text_instant(instant_text(moment)) == moment


def test_a_column_that_is_not_a_timestamp_is_a_store_error() -> None:
    with pytest.raises(StoreError, match="not a timestamp"):
        text_instant("half six")


def test_enums_round_trip_by_value() -> None:
    assert enum_text(Colour.YELLOW) == "yellow"
    assert text_enum(Colour, "yellow") is Colour.YELLOW


def test_an_unknown_enum_value_names_the_type() -> None:
    with pytest.raises(StoreError, match="not a Colour"):
        text_enum(Colour, "green")


def test_an_enum_that_is_not_stored_as_text_is_refused() -> None:
    with pytest.raises(StoreError, match="not stored as text"):
        enum_text(Numbered.ONE)


def test_lines_round_trip_through_one_column() -> None:
    address = ("Box 41", "Manti UT 84642")
    assert text_lines(lines_text(address)) == address
    assert text_lines("") == ()


def test_a_line_with_a_break_in_it_is_refused() -> None:
    with pytest.raises(StoreError, match="line break"):
        lines_text(("Box 41\nManti",))


def test_text_and_integer_columns_are_checked() -> None:
    assert text_value("MAIN") == "MAIN"
    assert int_value(118) == 118
    with pytest.raises(StoreError, match="not stored text"):
        text_value(118)
    with pytest.raises(StoreError, match="not a stored integer"):
        int_value("118")


def test_a_boolean_is_not_an_integer_column() -> None:
    with pytest.raises(StoreError, match="not a stored integer"):
        int_value(True)


def test_flags_round_trip_through_an_integer() -> None:
    assert flag_int(True) == 1
    assert flag_int(False) == 0
    assert int_flag(1)
    assert not int_flag(0)
