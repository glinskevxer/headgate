"""The generated files, and the marking that has to keep up with them."""

from __future__ import annotations

from pathlib import Path

import pytest

from headgate.tools import build_docs, schema_dump
from headgate.tools.generated import (
    ATTRIBUTES,
    COMMAND_REFERENCE,
    GENERATED,
    MARKER,
    SCHEMA_REFERENCE,
    Artefact,
    marked_paths,
    rebuild_all,
    unmarked,
)

ROOT = Path(__file__).resolve().parents[3]


def attributes() -> str:
    return (ROOT / ATTRIBUTES).read_text(encoding="utf-8")


def test_every_generated_file_that_ships_is_marked() -> None:
    missing = unmarked(attributes())
    assert missing == (), "these generated files are not marked in .gitattributes: " + ", ".join(
        item.path.as_posix() for item in missing
    )


def test_the_line_endings_are_normalised() -> None:
    assert "* text=auto eol=lf" in attributes()


def test_a_third_generator_added_without_marking_it_fails() -> None:
    thin = f"docs/commands.md {MARKER}\n"
    missing = unmarked(thin)
    assert [item.path.as_posix() for item in missing] == ["docs/schema.md"]


def test_comments_and_blank_lines_are_not_read_as_markings() -> None:
    text = f"# docs/schema.md {MARKER}\n\ndocs/commands.md {MARKER}\n"
    assert marked_paths(text) == {"docs/commands.md"}


def test_a_marking_needs_the_marker_on_it() -> None:
    assert marked_paths("docs/schema.md linguist-language=Text\n") == set()


def test_each_tool_writes_the_artefact_the_list_names() -> None:
    assert COMMAND_REFERENCE.path == build_docs.REFERENCE
    assert SCHEMA_REFERENCE.path == schema_dump.REFERENCE


def test_each_generated_file_carries_its_own_preamble() -> None:
    assert COMMAND_REFERENCE.preamble == build_docs.render().splitlines()[2]
    assert SCHEMA_REFERENCE.preamble == schema_dump.render().splitlines()[2]


def test_the_preamble_says_how_to_rebuild_the_file() -> None:
    for item in GENERATED:
        assert item.rebuild in item.preamble
        assert "Do not edit it by hand" in item.preamble


def test_the_rebuild_commands_name_modules_that_exist() -> None:
    from importlib import import_module

    for command in rebuild_all():
        module = command.removeprefix("python -m ")
        assert import_module(module).REFERENCE in {item.path for item in GENERATED}


def test_an_artefact_writes_its_own_attribute_line() -> None:
    line = SCHEMA_REFERENCE.attribute_line
    assert line == "docs/schema.md linguist-generated=true"
    assert marked_paths(line) == {"docs/schema.md"}


def test_the_artefacts_are_distinct_files() -> None:
    paths = [item.path for item in GENERATED]
    assert len(set(paths)) == len(paths)


def test_an_artefact_carries_what_it_is_for_a_reader() -> None:
    described = Artefact(
        path=Path("docs/nothing.md"),
        module="headgate.tools.nothing",
        source="out of thin air",
        what="nothing at all",
    )
    assert described.what == "nothing at all"
    assert "out of thin air" in described.preamble


def test_the_shipped_files_are_the_ones_on_disk() -> None:
    for item in GENERATED:
        assert (ROOT / item.path).is_file()


@pytest.mark.parametrize("artefact", GENERATED, ids=lambda item: item.path.name)
def test_every_shipped_generated_file_starts_with_its_heading(artefact: Artefact) -> None:
    text = (ROOT / artefact.path).read_text(encoding="utf-8")
    assert text.startswith("# headgate ")
    assert artefact.preamble in text
