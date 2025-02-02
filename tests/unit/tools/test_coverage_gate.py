import json
from decimal import Decimal
from pathlib import Path

import pytest

from headgate.tools.coverage_gate import (
    ModuleCoverage,
    main,
    read_report,
    under_floor,
)


def report(tmp_path: Path, total: float, files: dict[str, tuple[int, int]]) -> Path:
    path = tmp_path / "coverage.json"
    path.write_text(
        json.dumps(
            {
                "totals": {"percent_covered": total},
                "files": {
                    name: {"summary": {"covered_lines": covered, "num_statements": statements}}
                    for name, (covered, statements) in files.items()
                },
            }
        ),
        encoding="utf-8",
    )
    return path


def test_a_module_reports_its_percentage() -> None:
    assert ModuleCoverage("a.py", 9, 10).percent == Decimal("90.0")
    assert ModuleCoverage("a.py", 1, 3).percent == Decimal("33.3")


def test_a_module_with_nothing_in_it_is_covered() -> None:
    assert ModuleCoverage("__init__.py", 0, 0).percent == Decimal("100")


def test_the_report_is_read_whole(tmp_path: Path) -> None:
    path = report(tmp_path, 94.5, {"a.py": (9, 10), "b.py": (5, 5)})
    total, modules = read_report(path)
    assert total == Decimal("94.5")
    assert [item.path for item in modules] == ["a.py", "b.py"]


def test_a_missing_report_is_reported(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError, match="run the tests with coverage"):
        read_report(tmp_path / "nothing.json")


def test_the_modules_under_the_floor_are_picked_out(tmp_path: Path) -> None:
    path = report(tmp_path, 94.5, {"a.py": (9, 10), "b.py": (1, 10)})
    _, modules = read_report(path)
    assert [item.path for item in under_floor(modules)] == ["b.py"]


def test_a_good_report_passes(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    path = report(tmp_path, 94.5, {"a.py": (9, 10), "b.py": (5, 5)})
    assert main([str(path)]) == 0
    assert "94.5 percent over 2 modules" in capsys.readouterr().out


def test_a_low_package_number_fails(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    path = report(tmp_path, 71.0, {"a.py": (9, 10)})
    assert main([str(path)]) == 1
    assert "under the" in capsys.readouterr().out


def test_one_bad_module_fails_a_good_package(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = report(tmp_path, 94.5, {"a.py": (99, 100), "b.py": (1, 10)})
    assert main([str(path)]) == 1
    assert "b.py is at 10.0 percent" in capsys.readouterr().out


def test_a_missing_report_fails_the_gate(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main([str(tmp_path / "nothing.json")]) == 1
    assert "is not there" in capsys.readouterr().out
