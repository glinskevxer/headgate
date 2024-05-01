"""What every command needs: which book, and how to open it.

Commands take a connection rather than opening one themselves, so a test can
hand them a book in memory and so a command that fails partway leaves the file
closed either way.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

from ..errors import PolicyError
from ..store.db import Database, one
from ..store.migrations import current_version, is_current, migrate

DEFAULT_BOOK = Path("district.sqlite3")


@dataclass(frozen=True, slots=True)
class Context:
    """The book a command was pointed at."""

    database: Database
    quiet: bool = False

    @classmethod
    def at(cls, path: Path, quiet: bool = False) -> Context:
        return cls(Database(path), quiet)

    @contextmanager
    def open(self) -> Iterator[sqlite3.Connection]:
        with self.database.open() as connection:
            yield connection

    @contextmanager
    def open_current(self) -> Iterator[sqlite3.Connection]:
        """Open a book that has been set up, refusing one that has not."""

        with self.database.open() as connection:
            if current_version(connection) == 0:
                raise PolicyError(
                    f"{self.database.path} has never been set up, run headgate init first"
                )
            if not is_current(connection):
                raise PolicyError(
                    f"{self.database.path} is behind this version, run headgate migrate"
                )
            if district_name(connection) is None:
                raise PolicyError(f"{self.database.path} has no district in it")
            yield connection

    def set_up(self, name: str, state_code: str, stream: str, standard: str) -> int:
        """Migrate the book and write the district row. Returns the version."""

        with self.database.open() as connection:
            migrate(connection)
            existing = district_name(connection)
            if existing is not None:
                raise PolicyError(f"{self.database.path} already holds {existing}")
            connection.execute(
                "INSERT INTO district (id, name, state_code, miners_inch_standard, stream_name)"
                " VALUES (1, ?, ?, ?, ?)",
                (name, state_code, standard, stream),
            )
            return current_version(connection)


def district_name(connection: sqlite3.Connection) -> str | None:
    row = one(connection, "SELECT name FROM district WHERE id = 1")
    if row is None:
        return None
    name = row["name"]
    return str(name)
