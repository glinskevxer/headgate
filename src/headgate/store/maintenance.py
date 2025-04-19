"""Keeping the book in shape.

A district book that has run for fifteen seasons is mostly readings, and the
file behind it is full of pages that were freed when a season was restated and
never given back. Vacuuming returns them. Analysing gives the planner the
statistics it needs to keep choosing the indexes it was given.

Neither is dangerous and both take a lock, so they are commands somebody runs
on purpose in the winter rather than something the program does behind an
irrigator's back in July.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path

from ..errors import PolicyError, StoreError
from .db import Database, query, scalar
from .migrations import is_current


@dataclass(frozen=True, slots=True)
class BookSize:
    """How much room the book takes and how much of it is wasted."""

    pages: int
    free_pages: int
    page_size: int

    @property
    def bytes_used(self) -> int:
        return self.pages * self.page_size

    @property
    def bytes_free(self) -> int:
        return self.free_pages * self.page_size

    @property
    def waste_fraction(self) -> float:
        if self.pages == 0:
            return 0.0
        return round(self.free_pages / self.pages, 3)

    @property
    def is_worth_vacuuming(self) -> bool:
        return self.waste_fraction > 0.15 and self.free_pages > 16

    def describe(self) -> str:
        return f"{self.bytes_used} bytes over {self.pages} pages, {self.bytes_free} of it free"


def measure(connection: sqlite3.Connection) -> BookSize:
    return BookSize(
        pages=int(scalar(connection, "PRAGMA page_count") or 0),
        free_pages=int(scalar(connection, "PRAGMA freelist_count") or 0),
        page_size=int(scalar(connection, "PRAGMA page_size") or 0),
    )


def table_sizes(connection: sqlite3.Connection) -> dict[str, int]:
    """How many rows are in each table, biggest first."""

    names = query(
        connection,
        "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%'"
        " ORDER BY name",
    )
    counts: dict[str, int] = {}
    for row in names:
        table = str(row["name"])
        counts[table] = int(scalar(connection, f"SELECT count(*) FROM {table}") or 0)
    return dict(sorted(counts.items(), key=lambda item: (-item[1], item[0])))


def analyse(connection: sqlite3.Connection) -> None:
    """Give the planner fresh statistics."""

    if connection.in_transaction:
        raise PolicyError("analysing takes its own lock and cannot run inside a transaction")
    connection.execute("ANALYZE")


def vacuum(path: Path) -> BookSize:
    """Rebuild the file, giving the freed pages back to the disk."""

    with Database(path).open() as connection:
        if not is_current(connection):
            raise PolicyError(
                f"{path} is behind this version, migrate it before rebuilding the file"
            )
        before = measure(connection)
        try:
            connection.execute("VACUUM")
        except sqlite3.Error as exc:
            raise StoreError(f"the vacuum of {path} failed: {exc}") from exc
        return before


def optimise(connection: sqlite3.Connection) -> None:
    """The cheap one, which SQLite recommends before closing a long session."""

    connection.execute("PRAGMA optimize")


def wal_pages(connection: sqlite3.Connection) -> int:
    """How much has piled up in the write ahead log."""

    rows = query(connection, "PRAGMA wal_checkpoint(PASSIVE)")
    if not rows:
        return 0
    return int(rows[0][1] or 0)
