import csv
import sqlite3
from pathlib import Path

import pytest

from headgate.errors import PolicyError
from headgate.store.db import Database
from headgate.store.export import (
    MANIFEST,
    check_bundle,
    export_book,
    export_table,
    table_names,
)


def stocked(book: sqlite3.Connection) -> None:
    book.execute(
        "INSERT INTO district (id, name, state_code, miners_inch_standard, stream_name)"
        " VALUES (1, 'Sanpete', 'UT', 'COLORADO', 'Sanpete Creek')"
    )
    book.execute(
        "INSERT INTO account (number, name, joined, status)"
        " VALUES (118, 'Alma Peterson', '1994-03-01', 'active')"
    )


def test_every_table_in_the_book_is_exported(book: sqlite3.Connection, tmp_path: Path) -> None:
    stocked(book)
    export = export_book(book, tmp_path / "bundle")
    assert len(export.tables) == len(table_names(book))
    assert (tmp_path / "bundle" / MANIFEST).exists()


def test_the_export_says_what_is_in_it(book: sqlite3.Connection, tmp_path: Path) -> None:
    stocked(book)
    export = export_book(book, tmp_path / "bundle")
    assert export.rows >= 2
    assert "tables with" in export.describe()
    assert export.table("account").rows == 1


def test_a_table_comes_out_with_its_header(book: sqlite3.Connection, tmp_path: Path) -> None:
    stocked(book)
    tmp_path.joinpath("bundle").mkdir()
    table = export_table(book, "account", tmp_path / "bundle")
    with table.path.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.reader(handle))
    assert rows[0][0] == "number"
    assert rows[1][1] == "Alma Peterson"


def test_an_empty_table_still_comes_out(book: sqlite3.Connection, tmp_path: Path) -> None:
    stocked(book)
    export = export_book(book, tmp_path / "bundle")
    assert export.table("reading").is_empty
    assert export.table("reading").path.exists()


def test_a_bundle_checks_out_against_its_manifest(book: sqlite3.Connection, tmp_path: Path) -> None:
    stocked(book)
    export_book(book, tmp_path / "bundle")
    assert check_bundle(tmp_path / "bundle") == ()


def test_a_changed_file_fails_the_check(book: sqlite3.Connection, tmp_path: Path) -> None:
    stocked(book)
    export_book(book, tmp_path / "bundle")
    (tmp_path / "bundle" / "account.csv").write_text("number,name\n", encoding="utf-8")
    complaints = check_bundle(tmp_path / "bundle")
    assert "does not match its checksum" in complaints[0]


def test_a_missing_file_fails_the_check(book: sqlite3.Connection, tmp_path: Path) -> None:
    stocked(book)
    export_book(book, tmp_path / "bundle")
    (tmp_path / "bundle" / "account.csv").unlink()
    complaints = check_bundle(tmp_path / "bundle")
    assert "is not there" in complaints[0]


def test_a_directory_with_no_manifest_is_not_a_bundle(tmp_path: Path) -> None:
    (tmp_path / "loose").mkdir()
    assert "no manifest" in check_bundle(tmp_path / "loose")[0]


def test_an_export_will_not_write_over_a_bundle(book: sqlite3.Connection, tmp_path: Path) -> None:
    stocked(book)
    export_book(book, tmp_path / "bundle")
    with pytest.raises(PolicyError, match="already has files"):
        export_book(book, tmp_path / "bundle")


def test_a_book_that_was_never_set_up_exports_nothing(tmp_path: Path) -> None:
    with (
        Database(tmp_path / "fresh.sqlite3").open() as connection,
        pytest.raises(PolicyError, match="never been set up"),
    ):
        export_book(connection, tmp_path / "bundle")


def test_a_table_that_is_not_in_the_export_is_refused(
    book: sqlite3.Connection, tmp_path: Path
) -> None:
    stocked(book)
    export = export_book(book, tmp_path / "bundle")
    with pytest.raises(PolicyError, match="not in this export"):
        export.table("nothing_at_all")
