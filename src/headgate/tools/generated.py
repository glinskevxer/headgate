"""Every file in this repository that a program writes, named in one place.

Two files here are generated: the command reference off the click tree, and the
schema off the migrations. Both are checked in, because a reference nobody can
read without running the program is not a reference.

Checked in and generated at once is an awkward pair. A reviewer reads them as
though somebody typed them, and GitHub counts them toward the repository's
language statistics as though somebody typed them. Marking them
`linguist-generated` in `.gitattributes` fixes both, and the marking has the
same failure mode as the docs themselves: it goes stale the moment a third
generator is added and nobody remembers.

So the artefacts are listed here, the tools that write them read the list, and
a test fails the build if the list and `.gitattributes` disagree.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

ATTRIBUTES = Path(".gitattributes")
MARKER = "linguist-generated=true"


@dataclass(frozen=True, slots=True)
class Artefact:
    """One file a program writes, and how to write it again."""

    path: Path
    module: str
    source: str
    what: str

    @property
    def preamble(self) -> str:
        """The line the file carries telling a reader not to edit it."""

        return (
            f"This file is generated {self.source} by"
            f" `python -m {self.module}`. Do not edit it by hand."
        )

    @property
    def rebuild(self) -> str:
        return f"python -m {self.module}"

    @property
    def attribute_line(self) -> str:
        return f"{self.path.as_posix()} {MARKER}"


COMMAND_REFERENCE = Artefact(
    path=Path("docs/commands.md"),
    module="headgate.tools.build_docs",
    source="from the command line",
    what="the command reference",
)

SCHEMA_REFERENCE = Artefact(
    path=Path("docs/schema.md"),
    module="headgate.tools.schema_dump",
    source="from the migrations",
    what="the schema",
)

GENERATED: tuple[Artefact, ...] = (COMMAND_REFERENCE, SCHEMA_REFERENCE)


def marked_paths(attributes: str) -> set[str]:
    """The paths `.gitattributes` marks as generated."""

    found: set[str] = set()
    for line in attributes.splitlines():
        text = line.strip()
        if not text or text.startswith("#") or MARKER not in text:
            continue
        found.add(text.split()[0])
    return found


def unmarked(attributes: str) -> tuple[Artefact, ...]:
    """Generated artefacts `.gitattributes` does not know about."""

    marked = marked_paths(attributes)
    return tuple(item for item in GENERATED if item.path.as_posix() not in marked)


def rebuild_all() -> tuple[str, ...]:
    """The commands that rebuild every generated file, for an error message."""

    return tuple(item.rebuild for item in GENERATED)
