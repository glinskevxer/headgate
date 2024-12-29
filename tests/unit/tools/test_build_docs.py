from pathlib import Path

import pytest

from headgate.tools.build_docs import (
    REFERENCE,
    commands,
    describe,
    is_current,
    main_program,
    render,
    write,
)


def test_every_command_in_the_tree_is_walked() -> None:
    names = {" ".join(path) for path, _ in commands()}
    assert "order place" in names
    assert "report season" in names
    assert "device install" in names


def test_the_root_group_is_walked_but_not_written() -> None:
    assert ([], commands()[0][1]) == commands()[0]
    assert "## headgate\n" not in render()


def test_a_command_section_carries_its_options() -> None:
    path, command = next(item for item in commands() if item[0] == ["order", "place"])
    section = describe(path, command)
    assert "## headgate order place" in section
    assert "--account" in section
    assert "(required)" in section


def test_a_command_section_carries_its_arguments() -> None:
    path, command = next(item for item in commands() if item[0] == ["order", "answer"])
    section = describe(path, command)
    assert "order_id" in section
    assert "(argument)" in section


def test_the_reference_that_ships_is_current() -> None:
    assert is_current(REFERENCE)


def test_the_reference_starts_with_the_warning_not_to_edit_it() -> None:
    text = render()
    assert text.startswith("# headgate commands")
    assert "Do not edit it by hand" in text


def test_writing_the_reference_reports_its_length(tmp_path: Path) -> None:
    destination = tmp_path / "commands.md"
    assert write(destination) > 20
    assert is_current(destination)


def test_a_stale_reference_is_not_current(tmp_path: Path) -> None:
    destination = tmp_path / "commands.md"
    destination.write_text("# headgate commands\n", encoding="utf-8")
    assert not is_current(destination)


def test_a_missing_reference_is_not_current(tmp_path: Path) -> None:
    assert not is_current(tmp_path / "nothing.md")


def test_the_check_passes_against_what_ships(capsys: pytest.CaptureFixture[str]) -> None:
    assert main_program(["--check"]) == 0
    assert "is current" in capsys.readouterr().out
