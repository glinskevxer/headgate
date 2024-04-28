"""Check the migrations before anybody ships them.

Three things go wrong with a directory of numbered SQL files and all three are
cheap to catch here rather than on a district's book at four in the afternoon.
A file gets numbered out of sequence when two branches land the same week. A
file gets edited after it has already been applied somewhere, which makes the
version number a lie. And a file does not parse, which nobody finds until it
runs.

Run it as a module. It prints what it checked and exits non zero on the first
thing that is wrong.
"""

from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

from ..errors import StoreError
from ..store.db import Database
from ..store.migrations import SQL_DIRECTORY, available, migrate

FORBIDDEN_WORDS = ("DROP TABLE", "DROP COLUMN")


def check_numbering(directory: Path = SQL_DIRECTORY) -> list[str]:
    """Every file is named for its place and the places run one to n."""

    migrations = available(directory)
    if not migrations:
        raise StoreError(f"there are no migrations in {directory}")
    return [f"{item.version:04d} {item.name}" for item in migrations]


def check_parses(directory: Path = SQL_DIRECTORY) -> int:
    """Every statement runs, in order, against a book built from scratch.

    Preparing each statement on its own would be tidier and it does not work.
    An index on a table an earlier statement creates cannot be prepared until
    that table exists, so the only honest check is to run the set through.
    """

    statements = 0
    with Database.in_memory().open() as connection:
        for migration in available(directory):
            for statement in migration.statements():
                try:
                    connection.execute(statement)
                except sqlite3.Error as exc:
                    raise StoreError(
                        f"migration {migration.version:04d} will not parse: {exc}"
                    ) from exc
                statements += 1
    return statements


def check_applies(directory: Path = SQL_DIRECTORY) -> int:
    """The whole set applies to an empty book in one pass."""

    with Database.in_memory().open() as connection:
        applied = migrate(connection, directory)
    return len(applied)


def check_no_destructive_edits(directory: Path = SQL_DIRECTORY) -> list[str]:
    """Nothing drops a table or a column, because there is no down direction."""

    offences: list[str] = []
    for migration in available(directory):
        text = migration.read().upper()
        offences.extend(
            f"{migration.version:04d} {migration.name} contains {word}"
            for word in FORBIDDEN_WORDS
            if word in text
        )
    return offences


def main(argv: list[str] | None = None) -> int:
    arguments = sys.argv[1:] if argv is None else argv
    directory = Path(arguments[0]) if arguments else SQL_DIRECTORY
    try:
        names = check_numbering(directory)
        statements = check_parses(directory)
        applied = check_applies(directory)
        offences = check_no_destructive_edits(directory)
    except StoreError as exc:
        print(f"migrations: {exc}")
        return 1
    if offences:
        for offence in offences:
            print(f"migrations: {offence}")
        return 1
    print(f"migrations: {len(names)} files, {statements} statements, {applied} applied clean")
    for name in names:
        print(f"  {name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
