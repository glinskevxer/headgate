"""Build the command reference out of the command line itself.

Nobody keeps a hand written list of commands current. This walks the click
group, pulls the help off every command, and writes the reference. The build
runs it with --check, which rebuilds the reference into memory and compares, so
a command added without regenerating the docs fails there rather than shipping
a reference that lies.
"""

from __future__ import annotations

import sys
from pathlib import Path

import click

from ..cli.main import main
from .generated import COMMAND_REFERENCE

REFERENCE = COMMAND_REFERENCE.path
HEADING = "# headgate commands"
PREAMBLE = COMMAND_REFERENCE.preamble


def _walk(command: click.Command, path: list[str]) -> list[tuple[list[str], click.Command]]:
    found = [(path, command)]
    if isinstance(command, click.Group):
        for name in sorted(command.commands):
            found.extend(_walk(command.commands[name], [*path, name]))
    return found


def commands() -> list[tuple[list[str], click.Command]]:
    """Every command in the tree, group first, then the leaves in order."""

    return _walk(main, [])


def describe(path: list[str], command: click.Command) -> str:
    """One section of the reference for one command."""

    name = " ".join(["headgate", *path])
    lines = [f"## {name}", ""]
    summary = (command.help or command.short_help or "").strip().splitlines()
    if summary:
        lines.extend([summary[0].strip(), ""])
    options: list[str] = []
    for parameter in command.params:
        if isinstance(parameter, click.Option):
            flags = ", ".join(parameter.opts)
            required = " (required)" if parameter.required else ""
            options.append(f"- `{flags}`{required} {parameter.help or ''}".rstrip())
        elif isinstance(parameter, click.Argument):
            options.append(f"- `{parameter.name}` (argument)")
    if options:
        lines.extend(options)
        lines.append("")
    return "\n".join(lines)


def render() -> str:
    """The whole reference, as it should be on disk."""

    pieces = [HEADING, "", PREAMBLE, ""]
    for path, command in commands():
        if not path:
            continue
        pieces.append(describe(path, command))
    return "\n".join(pieces).rstrip() + "\n"


def write(destination: Path = REFERENCE) -> int:
    destination.parent.mkdir(parents=True, exist_ok=True)
    text = render()
    destination.write_text(text, encoding="utf-8")
    return len(text.splitlines())


def is_current(destination: Path = REFERENCE) -> bool:
    if not destination.exists():
        return False
    return destination.read_text(encoding="utf-8") == render()


def main_program(argv: list[str] | None = None) -> int:
    arguments = sys.argv[1:] if argv is None else argv
    destination = REFERENCE
    if "--check" in arguments:
        if is_current(destination):
            print(f"docs: {destination} is current")
            return 0
        print(f"docs: {destination} is out of date, run python -m headgate.tools.build_docs")
        return 1
    lines = write(destination)
    print(f"docs: wrote {lines} lines to {destination}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main_program())
