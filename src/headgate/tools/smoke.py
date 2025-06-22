"""Drive the installed command line over a whole small season.

The unit tests call the commands as Python functions, which proves the code
works and proves nothing about the thing that gets installed. This runs the
console script the way an office would, in a throwaway directory, and fails if
any step of it does not come back clean.

It is deliberately small: a canal, two turnouts, two shareholders, one season
of readings, and a close. Anything bigger belongs in the test suite.
"""

from __future__ import annotations

import subprocess
import sys
import tempfile
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

COMMAND = "headgate"


@dataclass(frozen=True, slots=True)
class Step:
    """One command and what its output has to contain."""

    arguments: list[str]
    expect: str = ""

    def describe(self) -> str:
        return " ".join(self.arguments[:3])


def steps(readings: Path) -> list[Step]:
    return [
        Step(
            ["init", "--name", "Smoke Ditch Company", "--state", "ut", "--stream", "Smoke Creek"],
            "set up",
        ),
        Step(
            [
                "ditch",
                "add",
                "--code",
                "MAIN",
                "--name",
                "Main Canal",
                "--capacity",
                "40",
                "--length",
                "21120",
                "--diversion-mile",
                "20",
            ],
            "added",
        ),
        Step(
            [
                "ditch",
                "turnout",
                "--ditch",
                "MAIN",
                "--code",
                "MAIN-2",
                "--name",
                "Head gate",
                "--station",
                "5280",
                "--capacity",
                "6",
                "--acres",
                "40",
            ],
            "added",
        ),
        Step(
            [
                "account",
                "add",
                "--number",
                "1",
                "--name",
                "A Shareholder",
                "--joined",
                "2000-01-01",
            ],
            "added",
        ),
        Step(
            [
                "account",
                "issue",
                "--serial",
                "A-1",
                "--account",
                "1",
                "--shares",
                "10",
                "--turnout",
                "MAIN-2",
                "--issued",
                "2005-04-01",
            ],
            "issued",
        ),
        Step(
            [
                "season",
                "declare",
                "--year",
                "2025",
                "--opens",
                "2025-04-15",
                "--closes",
                "2025-10-01",
                "--declared",
                "2025-03-20",
            ],
            "declared",
        ),
        Step(
            [
                "season",
                "rates",
                "--year",
                "2025",
                "--per-share",
                "5.00",
                "--band",
                "open:2.00",
                "--adopted",
                "2025-03-20",
            ],
            "adopted",
        ),
        Step(
            [
                "device",
                "install",
                "--tag",
                "WEIR-MAIN-2",
                "--kind",
                "cipolletti-weir",
                "--installed",
                "2016-03-01",
                "--turnout",
                "MAIN-2",
                "--crest",
                "3",
            ],
            "installed",
        ),
        Step(
            [
                "device",
                "install",
                "--tag",
                "FLUME-MAIN",
                "--kind",
                "parshall-flume",
                "--installed",
                "2011-05-01",
                "--ditch",
                "MAIN",
                "--throat",
                "4",
            ],
            "installed",
        ),
        Step(
            ["device", "calibrate", "--tag", "WEIR-MAIN-2", "--on", "2025-04-10", "--by", "smoke"],
            "calibrated",
        ),
        Step(
            ["device", "calibrate", "--tag", "FLUME-MAIN", "--on", "2025-04-10", "--by", "smoke"],
            "calibrated",
        ),
        Step(["reading", "import", str(readings)], "readings loaded"),
        Step(["report", "season", "2025"], "carriage"),
        Step(["season", "close", "--year", "2025", "--issued", "2025-11-01"], "bills written"),
        Step(["check", "--on", "2025-06-01"], "schema"),
        Step(["log"], "commands logged"),
    ]


def write_readings(path: Path) -> Path:
    rows = ["device,taken_at,observer,head,note"]
    start = datetime(2025, 4, 15, 6)
    for tag, head in (("WEIR-MAIN-2", "0.50"), ("FLUME-MAIN", "1.20")):
        for index in range(16):
            when = start + timedelta(days=index * 10)
            rows.append(f"{tag},{when:%Y-%m-%dT%H:%M},smoke,{head},")
    path.write_text("\n".join(rows) + "\n", encoding="utf-8")
    return path


def run_step(command: str, book: Path, step: Step) -> str:
    finished = subprocess.run(  # noqa: S603 - the arguments are built above, not taken in
        [command, "--book", str(book), *step.arguments],
        capture_output=True,
        text=True,
        check=False,
    )
    output = finished.stdout + finished.stderr
    if finished.returncode != 0:
        raise SystemExit(f"smoke: {step.describe()} failed\n{output}")
    if step.expect and step.expect not in output:
        raise SystemExit(f"smoke: {step.describe()} did not say {step.expect!r}\n{output}")
    return output


def main(argv: list[str] | None = None) -> int:
    arguments = sys.argv[1:] if argv is None else argv
    command = arguments[0] if arguments else COMMAND
    with tempfile.TemporaryDirectory() as directory:
        workspace = Path(directory)
        book = workspace / "smoke.sqlite3"
        readings = write_readings(workspace / "readings.csv")
        for step in steps(readings):
            run_step(command, book, step)
    print(f"smoke: {len(steps(Path('readings.csv')))} commands ran clean")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
