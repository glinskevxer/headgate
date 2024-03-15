"""Opening the district's book, and writing to it in one piece.

Everything is a single SQLite file. It is opened with foreign keys on, because
half the rules in this package are relationships and an unenforced one is a
rule that quietly stops being true, and in write ahead logging mode so a rider
entering readings does not block the clerk running a report.

Writes go through transaction(), which begins immediately rather than lazily.
A deferred transaction upgrades to a write lock partway through and can lose
that race after it has already read what it is about to write.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..errors import StoreError

MEMORY = ":memory:"

PRAGMAS = (
    "PRAGMA foreign_keys = ON",
    "PRAGMA busy_timeout = 5000",
    "PRAGMA synchronous = NORMAL",
)


@dataclass(frozen=True, slots=True)
class Database:
    """Where the district's book lives."""

    path: Path

    @classmethod
    def in_memory(cls) -> Database:
        return cls(Path(MEMORY))

    @property
    def is_memory(self) -> bool:
        return str(self.path) == MEMORY

    def connect(self) -> sqlite3.Connection:
        try:
            connection = sqlite3.connect(str(self.path), isolation_level=None)
        except sqlite3.Error as exc:
            raise StoreError(f"could not open {self.path}: {exc}") from exc
        connection.row_factory = sqlite3.Row
        for pragma in PRAGMAS:
            connection.execute(pragma)
        if not self.is_memory:
            connection.execute("PRAGMA journal_mode = WAL")
        return connection

    @contextmanager
    def open(self) -> Iterator[sqlite3.Connection]:
        connection = self.connect()
        try:
            yield connection
        finally:
            connection.close()


@contextmanager
def transaction(connection: sqlite3.Connection) -> Iterator[sqlite3.Connection]:
    """Run a block as one write, or leave the book untouched."""

    if connection.in_transaction:
        raise StoreError("a transaction is already open on this connection")
    connection.execute("BEGIN IMMEDIATE")
    try:
        yield connection
    except Exception:
        connection.execute("ROLLBACK")
        raise
    connection.execute("COMMIT")


def query(
    connection: sqlite3.Connection, sql: str, parameters: Sequence[Any] = ()
) -> list[sqlite3.Row]:
    """Every row a statement returns."""

    cursor = connection.execute(sql, parameters)
    try:
        return cursor.fetchall()
    finally:
        cursor.close()


def one(
    connection: sqlite3.Connection, sql: str, parameters: Sequence[Any] = ()
) -> sqlite3.Row | None:
    """The first row, or nothing."""

    cursor = connection.execute(sql, parameters)
    try:
        row: sqlite3.Row | None = cursor.fetchone()
    finally:
        cursor.close()
    return row


def scalar(connection: sqlite3.Connection, sql: str, parameters: Sequence[Any] = ()) -> Any:
    """The first column of the first row, which is what a count is."""

    row = one(connection, sql, parameters)
    return None if row is None else row[0]


def table_names(connection: sqlite3.Connection) -> tuple[str, ...]:
    rows = query(
        connection,
        "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%'"
        " ORDER BY name",
    )
    return tuple(str(row["name"]) for row in rows)
