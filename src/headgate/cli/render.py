"""Turning answers into something readable in a terminal.

The office prints these and staples them to the season file, so the columns
line up and the numbers carry the places the record carries. Nothing here knows
what a rate means; it only knows a rate is written to three places and a volume
to two, because that is what the delivery slips have always shown.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from enum import Enum

DASH = "-"


class Align(Enum):
    LEFT = "left"
    RIGHT = "right"


@dataclass(frozen=True, slots=True)
class Column:
    """One column of a printed table."""

    header: str
    align: Align = Align.LEFT

    def lay_out(self, text: str, width: int) -> str:
        if self.align is Align.RIGHT:
            return text.rjust(width)
        return text.ljust(width)


def rate(cfs: Decimal | None) -> str:
    """A rate, to the three places a staff gauge can justify."""

    if cfs is None:
        return DASH
    return f"{cfs:.3f}"


def volume(acre_feet: Decimal | None) -> str:
    """A volume, to the two places the delivery slip shows."""

    if acre_feet is None:
        return DASH
    return f"{acre_feet:.2f}"


def hours(count: Decimal | None) -> str:
    if count is None:
        return DASH
    return f"{count:.1f}"


def render_table(columns: list[Column], rows: list[list[str]]) -> str:
    """Lay a table out with the columns as wide as their widest cell."""

    for row in rows:
        if len(row) != len(columns):
            raise ValueError(f"a row of {len(row)} cells does not fit {len(columns)} columns")
    widths = [len(column.header) for column in columns]
    for row in rows:
        for index, cell in enumerate(row):
            widths[index] = max(widths[index], len(cell))
    lines = [
        "  ".join(
            column.lay_out(column.header, widths[index]) for index, column in enumerate(columns)
        ).rstrip()
    ]
    lines.append("  ".join(DASH * widths[index] for index in range(len(columns))))
    for row in rows:
        lines.append(
            "  ".join(
                column.lay_out(row[index], widths[index]) for index, column in enumerate(columns)
            ).rstrip()
        )
    return "\n".join(lines)


def field_list(pairs: list[tuple[str, str]]) -> str:
    """A block of label and value, which is how a single record prints."""

    if not pairs:
        return ""
    width = max(len(label) for label, _ in pairs)
    return "\n".join(f"{label.ljust(width)}  {value}" for label, value in pairs)


def plural(count: int, word: str, many: str | None = None) -> str:
    """Say a count in words that read right on a report line."""

    if count == 1:
        return f"1 {word}"
    return f"{count} {many if many is not None else word + 's'}"


def yes_no(flag: bool) -> str:
    return "yes" if flag else "no"


def truncate(text: str, width: int) -> str:
    """Cut a note down so it does not wrap a column."""

    if width < 4:
        raise ValueError("there is no useful way to truncate to fewer than four characters")
    if len(text) <= width:
        return text
    return text[: width - 3] + "..."
