from pathlib import Path

import pytest

from headgate.tools.smoke import Step, main, run_step, steps, write_readings


def test_the_smoke_run_covers_the_office_year(tmp_path: Path) -> None:
    named = [step.describe() for step in steps(tmp_path / "r.csv")]
    assert "init --name" in named[0]
    assert any("season close" in name for name in named)
    assert any("report season" in name for name in named)


def test_the_readings_file_covers_both_devices(tmp_path: Path) -> None:
    path = write_readings(tmp_path / "readings.csv")
    text = path.read_text(encoding="utf-8")
    assert "WEIR-MAIN-2" in text
    assert "FLUME-MAIN" in text
    assert len(text.splitlines()) == 33


def test_a_step_describes_itself() -> None:
    assert Step(["season", "close", "--year"], "").describe() == "season close --year"


def test_a_command_that_is_not_there_fails_the_smoke_run(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        run_step("headgate-that-is-not-installed", tmp_path / "book.sqlite3", Step(["about"]))


def test_the_smoke_run_drives_the_module_entry_point(tmp_path: Path) -> None:
    import sys

    command = str(Path(sys.executable).parent / "headgate")
    if not Path(command).exists():
        pytest.skip("the console script is not installed in this environment")
    assert main([command]) == 0
