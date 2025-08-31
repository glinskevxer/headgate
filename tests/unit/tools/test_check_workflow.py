"""The build's own command lines, checked the way a runner would read them."""

from __future__ import annotations

from pathlib import Path

import pytest

from headgate.tools.check_workflow import (
    WORKFLOW,
    check,
    check_file,
    invocations,
    main,
)

ROOT = Path(__file__).resolve().parents[3]


def test_every_command_line_in_the_shipped_workflow_parses() -> None:
    assert check_file(ROOT / WORKFLOW) == []


def test_the_workflow_actually_runs_the_command_line() -> None:
    found = invocations((ROOT / WORKFLOW).read_text(encoding="utf-8"))
    assert found
    assert any("about" in item.command for item in found)
    assert all(item.line > 0 for item in found)


def test_a_group_option_after_the_subcommand_is_caught() -> None:
    assert check(["about", "--book", "/tmp/x"]) == "headgate about has no option --book"


def test_the_same_option_before_the_subcommand_is_fine() -> None:
    assert check(["--book", "/tmp/x", "about"]) is None


def test_an_unknown_command_is_caught() -> None:
    assert check(["nosuchcommand"]) == "headgate has no command nosuchcommand"


def test_an_unknown_subcommand_is_caught() -> None:
    assert check(["report", "nosuchreport"]) == "headgate report has no command nosuchreport"


def test_an_unknown_option_names_the_command_it_was_written_after() -> None:
    assert check(["report", "season", "2025", "--nope"]) == (
        "headgate report season has no option --nope"
    )


def test_an_option_wanting_a_value_and_given_none_is_caught() -> None:
    assert check(["--book"]) == "--book on headgate wants a value and got none"


def test_an_inline_value_counts_as_the_value() -> None:
    assert check(["--book=/tmp/x", "about"]) is None


def test_a_flag_does_not_eat_the_next_token() -> None:
    assert check(["--quiet", "about"]) is None


def test_arguments_are_allowed_where_the_command_takes_them() -> None:
    assert check(["--book", "/tmp/x", "report", "season", "2025"]) is None


def test_an_argument_where_none_is_taken_is_caught() -> None:
    assert check(["about", "extra"]) == "headgate about takes no argument, and got extra"


def test_everything_after_a_double_dash_is_left_alone() -> None:
    assert check(["about", "--", "--book"]) is None


def test_a_workflow_that_is_not_there_is_reported(tmp_path: Path) -> None:
    complaints = check_file(tmp_path / "nothing.yml")
    assert "is not there" in complaints[0]


def test_the_program_passes_on_what_ships(capsys: pytest.CaptureFixture[str]) -> None:
    assert main([str(ROOT / WORKFLOW)]) == 0
    assert "command lines" in capsys.readouterr().out


def test_the_program_fails_on_a_bad_line(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = tmp_path / "ci.yml"
    path.write_text(
        "jobs:\n  a:\n    steps:\n      - run: headgate about --book /tmp/x\n", encoding="utf-8"
    )
    assert main([str(path)]) == 1
    assert "has no option --book" in capsys.readouterr().out


def test_lines_that_are_not_headgate_commands_are_left_alone(tmp_path: Path) -> None:
    path = tmp_path / "ci.yml"
    path.write_text(
        "      - run: python -m pytest -q\n      - run: echo headgate\n", encoding="utf-8"
    )
    assert invocations(path.read_text(encoding="utf-8")) == ()
    assert check_file(path) == []
