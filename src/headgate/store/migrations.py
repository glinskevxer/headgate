"""Bringing a district book up to the schema this version expects.

Migrations are plain SQL files named with a four digit version and a short
name, applied in order and recorded as they go. There is no down direction. A
district that needs to go back restores last night's file, which is what
actually happens when something goes wrong at four in the afternoon.

The ledger table is created here rather than in the first migration, so that
reading the version of a book that has never been migrated is an ordinary
question with an ordinary answer.
"""

from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from ..errors import StoreError
from .db import query, scalar, transaction

SQL_DIRECTORY = Path(__file__).parent / "sql"
FILENAME_PATTERN = re.compile(r"^([0-9]{4})_([a-z0-9_]+)\.sql$")

LEDGER_SQL = """
CREATE TABLE IF NOT EXISTS schema_migration (
    version    INTEGER PRIMARY KEY,
    name       TEXT NOT NULL,
    applied_at TEXT NOT NULL
)
"""


@dataclass(frozen=True, slots=True)
class Migration:
    """One numbered SQL file."""

    version: int
    name: str
    path: Path

    def read(self) -> str:
        return self.path.read_text(encoding="utf-8")

    def statements(self) -> tuple[str, ...]:
        return split_statements(self.read())


def split_statements(script: str) -> tuple[str, ...]:
    """Cut a migration into statements.

    executescript would be shorter and it commits whatever transaction is open
    before it runs, which silently takes a migration out of the transaction it
    was supposed to be inside. So the script is split here and the statements
    are run one at a time.
    """

    statements: list[str] = []
    buffer = ""
    for line in script.splitlines(keepends=True):
        if not buffer.strip() and line.strip().startswith("--"):
            continue
        buffer += line
        if sqlite3.complete_statement(buffer):
            text = buffer.strip()
            if text and text != ";":
                statements.append(text)
            buffer = ""
    if buffer.strip():
        raise StoreError("a migration ends in the middle of a statement")
    return tuple(statements)


def available(directory: Path = SQL_DIRECTORY) -> tuple[Migration, ...]:
    """Every migration on disk, in the order they have to be applied."""

    found: list[Migration] = []
    for path in sorted(directory.glob("*.sql")):
        match = FILENAME_PATTERN.match(path.name)
        if match is None:
            raise StoreError(f"{path.name} is not named like a migration")
        found.append(Migration(int(match.group(1)), match.group(2), path))
    versions = [item.version for item in found]
    if versions != sorted(set(versions)):
        raise StoreError("the migrations on disk repeat a version")
    for expected, actual in enumerate(versions, start=1):
        if expected != actual:
            raise StoreError(f"migration {actual} arrives where {expected} was expected")
    return tuple(found)


def ensure_ledger(connection: sqlite3.Connection) -> None:
    connection.execute(LEDGER_SQL)


def applied_versions(connection: sqlite3.Connection) -> tuple[int, ...]:
    ensure_ledger(connection)
    rows = query(connection, "SELECT version FROM schema_migration ORDER BY version")
    return tuple(int(row["version"]) for row in rows)


def current_version(connection: sqlite3.Connection) -> int:
    versions = applied_versions(connection)
    return versions[-1] if versions else 0


def pending(
    connection: sqlite3.Connection, directory: Path = SQL_DIRECTORY
) -> tuple[Migration, ...]:
    done = set(applied_versions(connection))
    return tuple(item for item in available(directory) if item.version not in done)


def migrate(
    connection: sqlite3.Connection, directory: Path = SQL_DIRECTORY
) -> tuple[Migration, ...]:
    """Apply everything the book has not seen yet."""

    ensure_ledger(connection)
    applied: list[Migration] = []
    for migration in pending(connection, directory):
        with transaction(connection):
            try:
                for statement in migration.statements():
                    connection.execute(statement)
            except sqlite3.Error as exc:
                raise StoreError(f"migration {migration.version} failed: {exc}") from exc
            connection.execute(
                "INSERT INTO schema_migration (version, name, applied_at) VALUES (?, ?, ?)",
                (migration.version, migration.name, datetime.now(UTC).isoformat()),
            )
        applied.append(migration)
    return tuple(applied)


def is_current(connection: sqlite3.Connection, directory: Path = SQL_DIRECTORY) -> bool:
    return not pending(connection, directory)


def latest_available(directory: Path = SQL_DIRECTORY) -> int:
    migrations = available(directory)
    if not migrations:
        raise StoreError("there are no migrations to run")
    return int(scalar_version(migrations))


def scalar_version(migrations: tuple[Migration, ...]) -> int:
    return migrations[-1].version


def describe(connection: sqlite3.Connection) -> str:
    version = current_version(connection)
    if version == 0:
        return "the book has never been migrated"
    row = query(
        connection,
        "SELECT name, applied_at FROM schema_migration WHERE version = ?",
        (version,),
    )
    if not row:
        raise StoreError(f"version {version} is recorded with no name")
    return f"at version {version}, {row[0]['name']}, applied {row[0]['applied_at']}"


def count_applied(connection: sqlite3.Connection) -> int:
    return int(scalar(connection, "SELECT count(*) FROM schema_migration") or 0)
