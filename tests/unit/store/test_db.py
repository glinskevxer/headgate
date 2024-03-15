import sqlite3
from pathlib import Path

import pytest

from headgate.errors import StoreError
from headgate.store.db import Database, one, query, scalar, table_names, transaction


def make_book(connection: sqlite3.Connection) -> None:
    connection.execute("CREATE TABLE ditch (code TEXT PRIMARY KEY, name TEXT NOT NULL)")
    connection.execute(
        "CREATE TABLE turnout (code TEXT PRIMARY KEY, ditch TEXT NOT NULL REFERENCES ditch(code))"
    )
    connection.execute("INSERT INTO ditch VALUES ('MAIN', 'Sanpete Main Canal')")


def test_a_memory_database_knows_it_is_one() -> None:
    assert Database.in_memory().is_memory
    assert not Database(Path("/tmp/book.sqlite3")).is_memory


def test_a_file_database_is_created_and_read_back(tmp_path: Path) -> None:
    book = Database(tmp_path / "district.sqlite3")
    with book.open() as connection:
        make_book(connection)
    with book.open() as connection:
        assert table_names(connection) == ("ditch", "turnout")


def test_foreign_keys_are_enforced() -> None:
    with Database.in_memory().open() as connection:
        make_book(connection)
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute("INSERT INTO turnout VALUES ('L9-1', 'L9')")


def test_a_transaction_commits_as_one_piece() -> None:
    with Database.in_memory().open() as connection:
        make_book(connection)
        with transaction(connection):
            connection.execute("INSERT INTO ditch VALUES ('L2', 'Second Lateral')")
        assert scalar(connection, "SELECT count(*) FROM ditch") == 2


def add_and_fail(connection: sqlite3.Connection) -> None:
    with transaction(connection):
        connection.execute("INSERT INTO ditch VALUES ('L2', 'Second Lateral')")
        raise RuntimeError("the rider went home")


def test_a_failed_transaction_leaves_the_book_alone() -> None:
    with Database.in_memory().open() as connection:
        make_book(connection)
        with pytest.raises(RuntimeError):
            add_and_fail(connection)
        assert scalar(connection, "SELECT count(*) FROM ditch") == 1


def test_a_second_transaction_on_one_connection_is_refused() -> None:
    with Database.in_memory().open() as connection:
        make_book(connection)
        with transaction(connection), pytest.raises(StoreError, match="already open"):
            transaction(connection).__enter__()


def test_query_returns_every_row_by_name() -> None:
    with Database.in_memory().open() as connection:
        make_book(connection)
        rows = query(connection, "SELECT code, name FROM ditch")
        assert rows[0]["name"] == "Sanpete Main Canal"


def test_one_returns_a_row_or_nothing() -> None:
    with Database.in_memory().open() as connection:
        make_book(connection)
        assert one(connection, "SELECT * FROM ditch WHERE code = ?", ("MAIN",)) is not None
        assert one(connection, "SELECT * FROM ditch WHERE code = ?", ("L9",)) is None


def test_scalar_returns_nothing_when_there_is_no_row() -> None:
    with Database.in_memory().open() as connection:
        make_book(connection)
        assert scalar(connection, "SELECT name FROM ditch WHERE code = ?", ("L9",)) is None


def test_opening_a_book_in_a_directory_that_is_not_there_is_a_store_error() -> None:
    book = Database(Path("/nonexistent-directory-for-headgate/district.sqlite3"))
    with pytest.raises(StoreError, match="could not open"):
        book.connect()


def test_the_connection_is_closed_when_the_block_ends(tmp_path: Path) -> None:
    book = Database(tmp_path / "district.sqlite3")
    with book.open() as connection:
        make_book(connection)
    with pytest.raises(sqlite3.ProgrammingError):
        connection.execute("SELECT 1")
