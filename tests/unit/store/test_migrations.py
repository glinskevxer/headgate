from pathlib import Path

import pytest

from headgate.errors import StoreError
from headgate.store.db import Database, table_names
from headgate.store.migrations import (
    available,
    count_applied,
    current_version,
    describe,
    is_current,
    latest_available,
    migrate,
    pending,
    split_statements,
)


def test_the_migrations_on_disk_are_numbered_from_one() -> None:
    found = available()
    assert found[0].version == 1
    assert [item.version for item in found] == list(range(1, len(found) + 1))


def test_a_fresh_book_is_at_version_zero() -> None:
    with Database.in_memory().open() as connection:
        assert current_version(connection) == 0
        assert describe(connection) == "the book has never been migrated"
        assert not is_current(connection)


def test_migrating_applies_everything_and_records_it() -> None:
    with Database.in_memory().open() as connection:
        applied = migrate(connection)
        assert len(applied) == len(available())
        assert current_version(connection) == latest_available()
        assert count_applied(connection) == len(applied)
        assert is_current(connection)


def test_migrating_twice_does_nothing_the_second_time() -> None:
    with Database.in_memory().open() as connection:
        migrate(connection)
        assert migrate(connection) == ()
        assert pending(connection) == ()


def test_the_first_migration_builds_the_tables_the_district_needs() -> None:
    with Database.in_memory().open() as connection:
        migrate(connection)
        tables = table_names(connection)
        for expected in ("account", "certificate", "ditch", "parcel", "reach", "turnout"):
            assert expected in tables


def test_the_book_reports_where_it_stands() -> None:
    with Database.in_memory().open() as connection:
        migrate(connection)
        assert "at version" in describe(connection)


def test_a_script_splits_into_statements_and_drops_its_comments() -> None:
    script = "-- a note\nCREATE TABLE a (id INTEGER);\nCREATE TABLE b (id INTEGER);\n"
    statements = split_statements(script)
    assert len(statements) == 2
    assert statements[0].startswith("CREATE TABLE a")


def test_a_script_that_stops_mid_statement_is_refused() -> None:
    with pytest.raises(StoreError, match="middle of a statement"):
        split_statements("CREATE TABLE a (id INTEGER)")


def test_a_badly_named_file_is_refused(tmp_path: Path) -> None:
    (tmp_path / "first.sql").write_text("SELECT 1;")
    with pytest.raises(StoreError, match="not named like a migration"):
        available(tmp_path)


def test_a_gap_in_the_numbering_is_refused(tmp_path: Path) -> None:
    (tmp_path / "0001_first.sql").write_text("SELECT 1;")
    (tmp_path / "0003_third.sql").write_text("SELECT 1;")
    with pytest.raises(StoreError, match="arrives where"):
        available(tmp_path)


def test_a_migration_that_will_not_run_is_reported_with_its_number(tmp_path: Path) -> None:
    (tmp_path / "0001_broken.sql").write_text("CREATE TABLE 9bad (id INTEGER);")
    with Database.in_memory().open() as connection, pytest.raises(StoreError, match="migration 1"):
        migrate(connection, tmp_path)


def test_a_failed_migration_is_not_recorded(tmp_path: Path) -> None:
    (tmp_path / "0001_broken.sql").write_text("CREATE TABLE 9bad (id INTEGER);")
    with Database.in_memory().open() as connection:
        with pytest.raises(StoreError):
            migrate(connection, tmp_path)
        assert current_version(connection) == 0


def test_a_directory_with_no_migrations_has_no_latest(tmp_path: Path) -> None:
    with pytest.raises(StoreError, match="no migrations"):
        latest_available(tmp_path)


def test_pending_lists_what_has_not_run_yet(tmp_path: Path) -> None:
    (tmp_path / "0001_first.sql").write_text("CREATE TABLE a (id INTEGER PRIMARY KEY);")
    (tmp_path / "0002_second.sql").write_text("CREATE TABLE b (id INTEGER PRIMARY KEY);")
    with Database.in_memory().open() as connection:
        assert len(pending(connection, tmp_path)) == 2
        migrate(connection, tmp_path)
        assert pending(connection, tmp_path) == ()
