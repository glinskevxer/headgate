from pathlib import Path

import pytest

from headgate.errors import StoreError
from headgate.store.migrations import SQL_DIRECTORY
from headgate.tools.check_migrations import (
    check_applies,
    check_no_destructive_edits,
    check_numbering,
    check_parses,
    main,
)


def test_the_migrations_that_ship_are_numbered_in_sequence() -> None:
    names = check_numbering()
    assert names[0].startswith("0001 ")
    assert len(names) == len(list(SQL_DIRECTORY.glob("*.sql")))


def test_every_shipped_statement_parses() -> None:
    assert check_parses() > 10


def test_the_whole_set_applies_to_an_empty_book() -> None:
    assert check_applies() == len(check_numbering())


def test_nothing_shipped_drops_a_table() -> None:
    assert check_no_destructive_edits() == []


def test_an_empty_directory_is_reported(tmp_path: Path) -> None:
    with pytest.raises(StoreError, match="no migrations"):
        check_numbering(tmp_path)


def test_a_statement_that_will_not_parse_is_reported(tmp_path: Path) -> None:
    (tmp_path / "0001_broken.sql").write_text("CREATE TABLE 9bad (id INTEGER);")
    with pytest.raises(StoreError, match="will not parse"):
        check_parses(tmp_path)


def test_a_drop_is_reported_rather_than_raised(tmp_path: Path) -> None:
    (tmp_path / "0001_first.sql").write_text("CREATE TABLE a (id INTEGER);")
    (tmp_path / "0002_second.sql").write_text("DROP TABLE a;")
    offences = check_no_destructive_edits(tmp_path)
    assert len(offences) == 1
    assert "DROP TABLE" in offences[0]


def test_the_program_passes_on_what_ships(capsys: pytest.CaptureFixture[str]) -> None:
    assert main([]) == 0
    printed = capsys.readouterr().out
    assert "applied clean" in printed
    assert "0001 initial" in printed


def test_the_program_fails_on_a_bad_directory(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main([str(tmp_path)]) == 1
    assert "migrations:" in capsys.readouterr().out


def test_the_program_fails_on_a_destructive_edit(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    (tmp_path / "0001_first.sql").write_text("CREATE TABLE a (id INTEGER);")
    (tmp_path / "0002_second.sql").write_text("DROP TABLE a;")
    assert main([str(tmp_path)]) == 1
    assert "DROP TABLE" in capsys.readouterr().out
