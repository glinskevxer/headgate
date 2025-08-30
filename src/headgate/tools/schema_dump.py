"""Write the schema out, so a change to it is visible in a diff.

The migrations are the truth and they are hard to read as a whole: a column
added in the eighth file belongs to a table created in the first. This builds
the book from the migrations in memory and writes what the schema actually
comes out as, table by table, so a reviewer can see the shape rather than the
history.

The build runs it with --check. A migration that changes the schema without the
reference being regenerated fails there, which is the only way the file stays
worth reading.
"""

from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

from ..store.db import Database, query
from ..store.migrations import migrate
from .generated import SCHEMA_REFERENCE

REFERENCE = SCHEMA_REFERENCE.path
HEADING = "# headgate schema"
PREAMBLE = SCHEMA_REFERENCE.preamble


def _tables(connection: sqlite3.Connection) -> list[str]:
    rows = query(
        connection,
        "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%'"
        " ORDER BY name",
    )
    return [str(row["name"]) for row in rows]


def _columns(connection: sqlite3.Connection, table: str) -> list[tuple[str, str, str]]:
    rows = query(connection, f"PRAGMA table_info({table})")
    found: list[tuple[str, str, str]] = []
    for row in rows:
        marks = []
        if row["pk"]:
            marks.append("key")
        if row["notnull"]:
            marks.append("not null")
        found.append((str(row["name"]), str(row["type"] or "-"), ", ".join(marks)))
    return found


def _indexes(connection: sqlite3.Connection, table: str) -> list[str]:
    rows = query(
        connection,
        "SELECT name FROM sqlite_master WHERE type = 'index' AND tbl_name = ?"
        " AND name NOT LIKE 'sqlite_%' ORDER BY name",
        (table,),
    )
    return [str(row["name"]) for row in rows]


def render() -> str:
    """The whole schema, as the migrations leave it."""

    pieces = [HEADING, "", PREAMBLE, ""]
    with Database.in_memory().open() as connection:
        migrate(connection)
        for table in _tables(connection):
            pieces.append(f"## {table}")
            pieces.append("")
            for name, kind, marks in _columns(connection, table):
                suffix = f" ({marks})" if marks else ""
                pieces.append(f"- `{name}` {kind}{suffix}")
            indexes = _indexes(connection, table)
            if indexes:
                pieces.append("")
                pieces.append("indexes: " + ", ".join(f"`{name}`" for name in indexes))
            pieces.append("")
    return "\n".join(pieces).rstrip() + "\n"


def write(destination: Path = REFERENCE) -> int:
    destination.parent.mkdir(parents=True, exist_ok=True)
    text = render()
    destination.write_text(text, encoding="utf-8")
    return len(text.splitlines())


def is_current(destination: Path = REFERENCE) -> bool:
    if not destination.exists():
        return False
    return destination.read_text(encoding="utf-8") == render()


def main(argv: list[str] | None = None) -> int:
    arguments = sys.argv[1:] if argv is None else argv
    destination = REFERENCE
    if "--check" in arguments:
        if is_current(destination):
            print(f"schema: {destination} is current")
            return 0
        print(f"schema: {destination} is out of date, run python -m headgate.tools.schema_dump")
        return 1
    lines = write(destination)
    print(f"schema: wrote {lines} lines to {destination}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
