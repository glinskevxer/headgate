"""What the package promises about itself when it is installed."""

from __future__ import annotations

import tomllib
from importlib import resources
from pathlib import Path
from typing import Any

import headgate
from headgate import __version__

ROOT = Path(__file__).resolve().parents[2]


def pyproject() -> Any:
    """The project file as it ships, read the way a build tool reads it."""

    with (ROOT / "pyproject.toml").open("rb") as handle:
        loaded: Any = tomllib.load(handle)
    return loaded


def test_the_package_ships_its_types() -> None:
    marker = resources.files(headgate) / "py.typed"
    assert marker.is_file()


def test_the_wheel_carries_the_marker() -> None:
    build = pyproject()["tool"]["hatch"]["build"]
    include = build["targets"]["wheel"]["force-include"]
    assert "src/headgate/py.typed" in include


def test_the_version_in_the_package_matches_the_project() -> None:
    project = pyproject()["project"]
    assert project["version"] == __version__


def test_the_migrations_ship_with_the_package() -> None:
    sql = resources.files(headgate) / "store" / "sql"
    names = sorted(item.name for item in sql.iterdir())
    assert names[0] == "0001_initial.sql"
    assert len(names) > 10


def test_the_console_script_points_at_the_entry_point() -> None:
    scripts = pyproject()["project"]["scripts"]
    assert scripts["headgate"] == "headgate.cli.main:run"


def test_the_runtime_dependency_is_pinned() -> None:
    dependencies = pyproject()["project"]["dependencies"]
    assert dependencies == ["click==8.1.8"]


def test_the_development_toolchain_is_pinned_exactly() -> None:
    extras = pyproject()["project"]["optional-dependencies"]
    for pin in extras["dev"]:
        assert "==" in pin


def test_the_package_requires_the_python_it_was_written_for() -> None:
    assert pyproject()["project"]["requires-python"] == ">=3.12"
