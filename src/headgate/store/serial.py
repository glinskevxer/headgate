"""Reading and writing the column types SQLite does not have.

Decimals are stored as text and never as floats. A binary float cannot hold a
tenth of an acre foot, and a season total that is out by a rounding error is a
letter from a shareholder. Dates go in as ISO text for the same reason: it
sorts correctly, it reads correctly in a query somebody types by hand, and it
does not depend on the local time zone of whoever ran the report.

Everything here fails loudly. A book with a bad value in it is worth stopping
for, because the alternative is a report that is quietly wrong.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from enum import Enum
from typing import TypeVar

from ..errors import StoreError

EnumT = TypeVar("EnumT", bound=Enum)

LINE_SEPARATOR = "\n"


def decimal_text(value: Decimal) -> str:
    """Store a decimal exactly as it was written."""

    return format(value, "f")


def text_decimal(text: object, column: str = "a decimal column") -> Decimal:
    if not isinstance(text, str):
        raise StoreError(f"{column} holds {text!r}, which is not stored text")
    try:
        return Decimal(text)
    except InvalidOperation as exc:
        raise StoreError(f"{column} holds {text!r}, which is not a number") from exc


def optional_decimal_text(value: Decimal | None) -> str | None:
    """Store a decimal that may not be there, without the caller branching."""

    return None if value is None else decimal_text(value)


def optional_decimal(text: object, column: str = "a decimal column") -> Decimal | None:
    if text is None:
        return None
    return text_decimal(text, column)


def date_text(day: date) -> str:
    return day.isoformat()


def text_date(text: object, column: str = "a date column") -> date:
    if not isinstance(text, str):
        raise StoreError(f"{column} holds {text!r}, which is not stored text")
    try:
        return date.fromisoformat(text)
    except ValueError as exc:
        raise StoreError(f"{column} holds {text!r}, which is not a date") from exc


def optional_date_text(day: date | None) -> str | None:
    """Store a date that may not be there."""

    return None if day is None else date_text(day)


def optional_date(text: object, column: str = "a date column") -> date | None:
    if text is None:
        return None
    return text_date(text, column)


def instant_text(moment: datetime) -> str:
    return moment.isoformat(sep=" ", timespec="seconds")


def text_instant(text: object, column: str = "a timestamp column") -> datetime:
    if not isinstance(text, str):
        raise StoreError(f"{column} holds {text!r}, which is not stored text")
    try:
        return datetime.fromisoformat(text)
    except ValueError as exc:
        raise StoreError(f"{column} holds {text!r}, which is not a timestamp") from exc


def code_text(code: object | None) -> str | None:
    """Store an identifier that may not be there, as the text it prints as."""

    return None if code is None else str(code)


def enum_text(value: Enum) -> str:
    text = value.value
    if not isinstance(text, str):
        raise StoreError(f"{value!r} is not stored as text")
    return text


def text_enum(kind: type[EnumT], text: object, column: str = "an enum column") -> EnumT:
    if not isinstance(text, str):
        raise StoreError(f"{column} holds {text!r}, which is not stored text")
    try:
        return kind(text)
    except ValueError as exc:
        raise StoreError(f"{column} holds {text!r}, which is not a {kind.__name__}") from exc


def lines_text(lines: tuple[str, ...]) -> str:
    for line in lines:
        if LINE_SEPARATOR in line:
            raise StoreError("a stored line may not contain a line break")
    return LINE_SEPARATOR.join(lines)


def text_lines(text: object, column: str = "a text column") -> tuple[str, ...]:
    if not isinstance(text, str):
        raise StoreError(f"{column} holds {text!r}, which is not stored text")
    if not text:
        return ()
    return tuple(text.split(LINE_SEPARATOR))


def text_value(text: object, column: str = "a text column") -> str:
    if not isinstance(text, str):
        raise StoreError(f"{column} holds {text!r}, which is not stored text")
    return text


def int_value(number: object, column: str = "an integer column") -> int:
    if isinstance(number, bool) or not isinstance(number, int):
        raise StoreError(f"{column} holds {number!r}, which is not a stored integer")
    return number


def flag_int(flag: bool) -> int:
    return 1 if flag else 0


def int_flag(number: object, column: str = "a flag column") -> bool:
    return int_value(number, column) != 0
