from pathlib import Path

import pytest

from headgate.tools.schema_dump import REFERENCE, is_current, main, render, write


def test_every_table_the_migrations_build_is_in_the_reference() -> None:
    text = render()
    for table in (
        "account",
        "certificate",
        "reading",
        "water_order",
        "journal_entry",
        "lease",
        "gage_day",
        "well_pumping",
    ):
        assert f"## {table}" in text


def test_the_columns_carry_their_marks() -> None:
    text = render()
    assert "`number` INTEGER (key, not null)" in text or "`number` INTEGER (key)" in text
    assert "`observer` TEXT (not null)" in text


def test_the_indexes_are_listed_under_their_table() -> None:
    text = render()
    assert "indexes:" in text
    assert "`reading_by_time`" in text


def test_the_reference_that_ships_is_current() -> None:
    assert is_current(REFERENCE)


def test_the_reference_says_not_to_edit_it() -> None:
    assert render().startswith("# headgate schema")
    assert "Do not edit it by hand" in render()


def test_writing_the_reference_reports_its_length(tmp_path: Path) -> None:
    destination = tmp_path / "schema.md"
    assert write(destination) > 50
    assert is_current(destination)


def test_a_stale_reference_is_not_current(tmp_path: Path) -> None:
    destination = tmp_path / "schema.md"
    destination.write_text("# headgate schema\n", encoding="utf-8")
    assert not is_current(destination)


def test_a_missing_reference_is_not_current(tmp_path: Path) -> None:
    assert not is_current(tmp_path / "nothing.md")


def test_the_check_passes_against_what_ships(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["--check"]) == 0
    assert "is current" in capsys.readouterr().out
