"""Check that the command lines in the build actually parse.

The build runs `headgate` a dozen times across its jobs, and those lines are
the one piece of this repository nothing tests. The suite calls the commands as
Python functions with the arguments already in the right shape, so a workflow
line that puts a group option after the subcommand passes every test here and
fails on a runner.

That is not hypothetical. `headgate about --book /tmp/none.sqlite3` shipped in
the package job and failed with `No such option: --book`, because `--book`
belongs to the group and has to come before the subcommand. This walks the
click tree over every command line in the workflow and says which token is
wrong, which is cheaper than finding out from a red build.
"""

from __future__ import annotations

import re
import shlex
import sys
from dataclasses import dataclass
from pathlib import Path

import click

from ..cli.main import main as cli

WORKFLOW = Path(".github/workflows/ci.yml")
RUN_LINE = re.compile(r"^\s*-?\s*run:\s*(?P<command>headgate\s.+?)\s*$")


@dataclass(frozen=True, slots=True)
class Invocation:
    """One `headgate ...` line out of a workflow file."""

    line: int
    command: str

    @property
    def arguments(self) -> list[str]:
        return shlex.split(self.command)[1:]


def invocations(text: str) -> tuple[Invocation, ...]:
    """Every `headgate ...` command line in a workflow, with its line number."""

    found: list[Invocation] = []
    for number, line in enumerate(text.splitlines(), start=1):
        match = RUN_LINE.match(line)
        if match is not None:
            found.append(Invocation(line=number, command=match.group("command")))
    return tuple(found)


def _options(command: click.Command) -> dict[str, click.Option]:
    found: dict[str, click.Option] = {}
    for parameter in command.params:
        if isinstance(parameter, click.Option):
            for name in (*parameter.opts, *parameter.secondary_opts):
                found[name] = parameter
    return found


def check(arguments: list[str]) -> str | None:
    """Walk one command line through the tree. Returns the complaint, or None.

    Options are looked up against the command they are written after, which is
    the whole point: click gives a group's options to the group, and writing
    one after the subcommand is the mistake this catches.
    """

    command: click.Command = cli
    path = ["headgate"]
    remaining = list(arguments)
    while remaining:
        token = remaining.pop(0)
        if token == "--":
            break
        if token.startswith("-"):
            name, _, inline = token.partition("=")
            option = _options(command).get(name)
            if option is None:
                return f"{' '.join(path)} has no option {name}"
            if not option.is_flag and not inline:
                if not remaining:
                    return f"{name} on {' '.join(path)} wants a value and got none"
                remaining.pop(0)
            continue
        if isinstance(command, click.Group):
            found = command.get_command(click.Context(command), token)
            if found is None:
                return f"{' '.join(path)} has no command {token}"
            command = found
            path.append(token)
            continue
        wanted = sum(1 for item in command.params if isinstance(item, click.Argument))
        if wanted == 0:
            return f"{' '.join(path)} takes no argument, and got {token}"
    return None


def check_file(path: Path = WORKFLOW) -> list[str]:
    """Every complaint about every command line in a workflow file."""

    if not path.exists():
        return [f"{path} is not there"]
    complaints: list[str] = []
    for found in invocations(path.read_text(encoding="utf-8")):
        problem = check(found.arguments)
        if problem is not None:
            complaints.append(f"{path}:{found.line}: {problem}")
    return complaints


def main(argv: list[str] | None = None) -> int:
    arguments = sys.argv[1:] if argv is None else argv
    path = Path(arguments[0]) if arguments else WORKFLOW
    complaints = check_file(path)
    counted = len(invocations(path.read_text(encoding="utf-8"))) if path.exists() else 0
    if complaints:
        for complaint in complaints:
            print(f"workflow: {complaint}")
        return 1
    print(f"workflow: {counted} command lines in {path} parse")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
