"""Copying a book safely, and checking the copy is worth having.

Copying the file with the operating system while somebody is writing to it
produces a file that opens, reads, and is wrong in the middle. SQLite's own
backup walks the pages under a lock and produces a book that is consistent at a
moment, which is the only kind worth keeping.

Every backup is checked before it is called a backup: the integrity check, the
foreign keys, and the schema version, because a copy that restores into a
version of this program that cannot read it is not a backup either.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from ..errors import PolicyError, StoreError
from .db import Database, query, scalar
from .migrations import current_version, is_current


@dataclass(frozen=True, slots=True)
class BackupResult:
    """What was copied, and what the copy came out as."""

    source: Path
    destination: Path
    pages: int
    bytes_written: int
    schema_version: int
    taken_at: datetime

    @property
    def is_empty(self) -> bool:
        return self.pages == 0

    def describe(self) -> str:
        return (
            f"{self.destination} holds {self.pages} pages, {self.bytes_written} bytes, "
            f"schema version {self.schema_version}"
        )


def check_integrity(connection: sqlite3.Connection) -> tuple[str, ...]:
    """Whatever SQLite has to say about the file, one line at a time."""

    rows = query(connection, "PRAGMA integrity_check")
    return tuple(str(row[0]) for row in rows)


def check_foreign_keys(connection: sqlite3.Connection) -> tuple[str, ...]:
    """Rows pointing at rows that are not there."""

    rows = query(connection, "PRAGMA foreign_key_check")
    return tuple(f"{row[0]} row {row[1]} references {row[2]}" for row in rows)


def is_sound(connection: sqlite3.Connection) -> bool:
    return check_integrity(connection) == ("ok",) and not check_foreign_keys(connection)


def back_up(source: Path, destination: Path) -> BackupResult:
    """Copy a book to another file, through SQLite rather than around it."""

    if destination == source:
        raise PolicyError("a backup that writes over the book it copied is not a backup")
    if destination.exists():
        raise PolicyError(f"{destination} is already there, and a backup does not overwrite")
    destination.parent.mkdir(parents=True, exist_ok=True)
    with Database(source).open() as origin:
        if current_version(origin) == 0:
            raise PolicyError(f"{source} has never been set up, so there is nothing to back up")
        pages = int(scalar(origin, "PRAGMA page_count") or 0)
        version = current_version(origin)
        with Database(destination).open() as copy:
            try:
                origin.backup(copy)
            except sqlite3.Error as exc:
                raise StoreError(f"the backup of {source} failed: {exc}") from exc
            if not is_sound(copy):
                raise StoreError(f"the copy at {destination} did not come out sound")
    return BackupResult(
        source=source,
        destination=destination,
        pages=pages,
        bytes_written=destination.stat().st_size,
        schema_version=version,
        taken_at=datetime.now(UTC),
    )


def verify(path: Path) -> tuple[bool, tuple[str, ...]]:
    """Open a file and say whether it is a book this version can use."""

    if not path.exists():
        return False, (f"{path} is not there",)
    with Database(path).open() as connection:
        complaints: list[str] = []
        integrity = check_integrity(connection)
        if integrity != ("ok",):
            complaints.extend(integrity)
        complaints.extend(check_foreign_keys(connection))
        if current_version(connection) == 0:
            complaints.append("it has never been migrated")
        elif not is_current(connection):
            complaints.append("it is behind this version of the program")
        return not complaints, tuple(complaints)


def restore(backup: Path, destination: Path) -> BackupResult:
    """Put a backup back, refusing to write over a book that is already there."""

    if destination.exists():
        raise PolicyError(
            f"{destination} is already there, move it out of the way before restoring"
        )
    sound, complaints = verify(backup)
    if not sound:
        raise PolicyError(f"{backup} is not worth restoring: {'; '.join(complaints)}")
    return back_up(backup, destination)
