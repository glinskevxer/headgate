import sqlite3
from pathlib import Path

import pytest

from headgate.errors import PolicyError
from headgate.store.db import Database, transaction
from headgate.store.maintenance import (
    BookSize,
    analyse,
    measure,
    optimise,
    table_sizes,
    vacuum,
    wal_pages,
)
from headgate.store.migrations import migrate


def test_a_book_reports_its_size(book: sqlite3.Connection) -> None:
    size = measure(book)
    assert size.pages > 0
    assert size.page_size > 0
    assert "bytes over" in size.describe()


def test_a_tidy_book_is_not_worth_vacuuming(book: sqlite3.Connection) -> None:
    assert not measure(book).is_worth_vacuuming


def test_a_book_full_of_free_pages_is_worth_vacuuming() -> None:
    size = BookSize(pages=100, free_pages=40, page_size=4096)
    assert size.is_worth_vacuuming
    assert size.waste_fraction == 0.4
    assert size.bytes_free == 40 * 4096


def test_an_empty_book_wastes_nothing() -> None:
    assert BookSize(pages=0, free_pages=0, page_size=4096).waste_fraction == 0.0


def test_the_tables_are_counted_biggest_first(book: sqlite3.Connection) -> None:
    book.execute(
        "INSERT INTO district (id, name, state_code, miners_inch_standard, stream_name)"
        " VALUES (1, 'Sanpete', 'UT', 'COLORADO', 'Sanpete Creek')"
    )
    counts = table_sizes(book)
    assert counts["district"] == 1
    assert list(counts)[0] == "schema_migration"


def test_analysing_gives_the_planner_statistics(book: sqlite3.Connection) -> None:
    analyse(book)
    rows = book.execute("SELECT name FROM sqlite_master WHERE name = 'sqlite_stat1'").fetchall()
    assert rows


def test_analysing_inside_a_transaction_is_refused(book: sqlite3.Connection) -> None:
    with transaction(book), pytest.raises(PolicyError, match="its own lock"):
        analyse(book)


def test_optimising_is_harmless(book: sqlite3.Connection) -> None:
    optimise(book)
    assert measure(book).pages > 0


def test_the_write_ahead_log_can_be_checkpointed(tmp_path: Path) -> None:
    path = tmp_path / "district.sqlite3"
    with Database(path).open() as connection:
        migrate(connection)
        assert wal_pages(connection) >= 0


def test_vacuuming_rebuilds_the_file(tmp_path: Path) -> None:
    path = tmp_path / "district.sqlite3"
    with Database(path).open() as connection:
        migrate(connection)
    before = vacuum(path)
    assert before.pages > 0
    with Database(path).open() as connection:
        assert measure(connection).pages > 0


def test_a_book_behind_this_version_is_not_vacuumed(tmp_path: Path) -> None:
    path = tmp_path / "old.sqlite3"
    with Database(path).open() as connection:
        connection.execute("CREATE TABLE a (id INTEGER PRIMARY KEY)")
    with pytest.raises(PolicyError, match="behind this version"):
        vacuum(path)
