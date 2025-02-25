import sqlite3
from pathlib import Path

import pytest

from headgate.errors import PolicyError
from headgate.store.backup import (
    back_up,
    check_foreign_keys,
    check_integrity,
    is_sound,
    restore,
    verify,
)
from headgate.store.db import Database
from headgate.store.migrations import migrate
from tests.support.district import foreign_keys_off


def district(path: Path) -> Path:
    with Database(path).open() as connection:
        migrate(connection)
        connection.execute(
            "INSERT INTO district (id, name, state_code, miners_inch_standard, stream_name)"
            " VALUES (1, 'Sanpete', 'UT', 'COLORADO', 'Sanpete Creek')"
        )
    return path


def test_a_fresh_book_is_sound(book: sqlite3.Connection) -> None:
    assert check_integrity(book) == ("ok",)
    assert check_foreign_keys(book) == ()
    assert is_sound(book)


def test_a_row_pointing_at_nothing_shows_in_the_key_check(
    book: sqlite3.Connection,
) -> None:
    with foreign_keys_off(book):
        book.execute(
            "INSERT INTO reading (device_tag, taken_at, observer, method, head_feet)"
            " VALUES ('WEIR-L2-99', '2025-06-01 06:00:00', 'D. Yardley', 'staff', '0.5')"
        )
    assert check_foreign_keys(book)
    assert not is_sound(book)


def test_a_backup_copies_the_book(tmp_path: Path) -> None:
    source = district(tmp_path / "district.sqlite3")
    result = back_up(source, tmp_path / "backup" / "district.sqlite3")
    assert result.pages > 0
    assert not result.is_empty
    assert result.bytes_written > 0
    assert "schema version" in result.describe()


def test_the_copy_holds_what_the_book_held(tmp_path: Path) -> None:
    source = district(tmp_path / "district.sqlite3")
    back_up(source, tmp_path / "copy.sqlite3")
    with Database(tmp_path / "copy.sqlite3").open() as connection:
        row = connection.execute("SELECT name FROM district WHERE id = 1").fetchone()
    assert row["name"] == "Sanpete"


def test_a_backup_does_not_write_over_anything(tmp_path: Path) -> None:
    source = district(tmp_path / "district.sqlite3")
    back_up(source, tmp_path / "copy.sqlite3")
    with pytest.raises(PolicyError, match="does not overwrite"):
        back_up(source, tmp_path / "copy.sqlite3")


def test_a_backup_over_the_book_itself_is_refused(tmp_path: Path) -> None:
    source = district(tmp_path / "district.sqlite3")
    with pytest.raises(PolicyError, match="not a backup"):
        back_up(source, source)


def test_a_book_that_was_never_set_up_has_nothing_to_back_up(tmp_path: Path) -> None:
    with pytest.raises(PolicyError, match="nothing to back up"):
        back_up(tmp_path / "fresh.sqlite3", tmp_path / "copy.sqlite3")


def test_a_good_copy_verifies(tmp_path: Path) -> None:
    source = district(tmp_path / "district.sqlite3")
    back_up(source, tmp_path / "copy.sqlite3")
    sound, complaints = verify(tmp_path / "copy.sqlite3")
    assert sound
    assert complaints == ()


def test_a_file_that_is_not_there_does_not_verify(tmp_path: Path) -> None:
    sound, complaints = verify(tmp_path / "nothing.sqlite3")
    assert not sound
    assert "is not there" in complaints[0]


def test_an_unmigrated_file_does_not_verify(tmp_path: Path) -> None:
    path = tmp_path / "empty.sqlite3"
    with Database(path).open() as connection:
        connection.execute("CREATE TABLE a (id INTEGER PRIMARY KEY)")
    sound, complaints = verify(path)
    assert not sound
    assert "never been migrated" in complaints[0]


def test_a_backup_restores_into_a_new_book(tmp_path: Path) -> None:
    source = district(tmp_path / "district.sqlite3")
    back_up(source, tmp_path / "copy.sqlite3")
    result = restore(tmp_path / "copy.sqlite3", tmp_path / "restored.sqlite3")
    assert result.schema_version > 0
    sound, _ = verify(tmp_path / "restored.sqlite3")
    assert sound


def test_a_restore_does_not_write_over_a_book(tmp_path: Path) -> None:
    source = district(tmp_path / "district.sqlite3")
    back_up(source, tmp_path / "copy.sqlite3")
    with pytest.raises(PolicyError, match="move it out of the way"):
        restore(tmp_path / "copy.sqlite3", source)


def test_a_file_worth_nothing_is_not_restored(tmp_path: Path) -> None:
    path = tmp_path / "empty.sqlite3"
    with Database(path).open() as connection:
        connection.execute("CREATE TABLE a (id INTEGER PRIMARY KEY)")
    with pytest.raises(PolicyError, match="not worth restoring"):
        restore(path, tmp_path / "restored.sqlite3")
