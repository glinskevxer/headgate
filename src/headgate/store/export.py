"""Writing the whole book out as plain files.

The state engineer asks for the delivery record, the auditor asks for the
assessment, and neither of them wants a SQLite file. This writes every table as
a CSV with its header, plus a manifest naming the tables, the row counts and a
checksum for each file, so somebody receiving the bundle can tell whether it
arrived whole.

The export refuses to write into a directory that already has files in it. A
half overwritten export looks exactly like a complete one, and the person who
finds out is whoever loads it two years later.
"""

from __future__ import annotations

import csv
import hashlib
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from ..errors import PolicyError
from .db import query
from .migrations import current_version

MANIFEST = "manifest.csv"
MANIFEST_COLUMNS = ("table", "rows", "bytes", "sha256")


@dataclass(frozen=True, slots=True)
class ExportedTable:
    """One table, as it landed on disk."""

    name: str
    rows: int
    path: Path
    digest: str

    @property
    def size_bytes(self) -> int:
        return self.path.stat().st_size

    @property
    def is_empty(self) -> bool:
        return self.rows == 0


@dataclass(frozen=True, slots=True)
class Export:
    """A whole bundle, and what is in it."""

    directory: Path
    taken_at: datetime
    schema_version: int
    tables: tuple[ExportedTable, ...]

    @property
    def rows(self) -> int:
        return sum(item.rows for item in self.tables)

    @property
    def with_rows(self) -> tuple[ExportedTable, ...]:
        return tuple(item for item in self.tables if not item.is_empty)

    def table(self, name: str) -> ExportedTable:
        for item in self.tables:
            if item.name == name:
                return item
        raise PolicyError(f"{name} is not in this export")

    def describe(self) -> str:
        return (
            f"{len(self.with_rows)} tables with {self.rows} rows at schema version "
            f"{self.schema_version}"
        )


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def table_names(connection: sqlite3.Connection) -> tuple[str, ...]:
    rows = query(
        connection,
        "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%'"
        " ORDER BY name",
    )
    return tuple(str(row["name"]) for row in rows)


def export_table(connection: sqlite3.Connection, name: str, directory: Path) -> ExportedTable:
    """Write one table out with its header, in primary key order."""

    rows = query(connection, f"SELECT * FROM {name}")
    path = directory / f"{name}.csv"
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        columns = [str(item["name"]) for item in query(connection, f"PRAGMA table_info({name})")]
        writer.writerow(columns)
        for row in rows:
            writer.writerow(["" if row[column] is None else row[column] for column in columns])
    return ExportedTable(name=name, rows=len(rows), path=path, digest=_digest(path))


def write_manifest(directory: Path, tables: tuple[ExportedTable, ...]) -> Path:
    path = directory / MANIFEST
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(MANIFEST_COLUMNS)
        for table in tables:
            writer.writerow([table.name, table.rows, table.size_bytes, table.digest])
    return path


def export_book(connection: sqlite3.Connection, directory: Path) -> Export:
    """Write every table out, with a manifest beside them."""

    if directory.exists() and any(directory.iterdir()):
        raise PolicyError(f"{directory} already has files in it, export somewhere empty")
    directory.mkdir(parents=True, exist_ok=True)
    version = current_version(connection)
    if version == 0:
        raise PolicyError("this book has never been set up, so there is nothing to export")
    tables = tuple(export_table(connection, name, directory) for name in table_names(connection))
    write_manifest(directory, tables)
    return Export(
        directory=directory,
        taken_at=datetime.now(UTC),
        schema_version=version,
        tables=tables,
    )


def check_bundle(directory: Path) -> tuple[str, ...]:
    """Read a bundle's manifest and say what does not match it."""

    manifest = directory / MANIFEST
    if not manifest.exists():
        return (f"{directory} has no manifest in it",)
    complaints: list[str] = []
    with manifest.open(newline="", encoding="utf-8") as handle:
        for entry in csv.DictReader(handle):
            path = directory / f"{entry['table']}.csv"
            if not path.exists():
                complaints.append(f"{entry['table']} is named in the manifest and is not there")
                continue
            if _digest(path) != entry["sha256"]:
                complaints.append(f"{entry['table']} does not match its checksum")
    return tuple(complaints)
