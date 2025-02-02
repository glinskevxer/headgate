"""Hold the coverage up, and say which module let it down.

A single number over the whole package hides the module that has no tests at
all, because everything else carries it. This reads the coverage report and
checks two things: the whole package against a floor, and every module against
a lower one. The second is the one that finds the file somebody added on a
Friday.
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path

REPORT = Path("coverage.json")
PACKAGE_FLOOR = Decimal("90")
MODULE_FLOOR = Decimal("70")


@dataclass(frozen=True, slots=True)
class ModuleCoverage:
    """One file, and how much of it the tests reached."""

    path: str
    covered: int
    statements: int

    @property
    def percent(self) -> Decimal:
        if self.statements == 0:
            return Decimal("100")
        return (Decimal(self.covered) / Decimal(self.statements) * 100).quantize(Decimal("0.1"))

    def is_under(self, floor: Decimal) -> bool:
        return self.percent < floor


def read_report(path: Path = REPORT) -> tuple[Decimal, tuple[ModuleCoverage, ...]]:
    """Pull the whole number and the per module numbers out of the report."""

    if not path.exists():
        raise FileNotFoundError(f"{path} is not there, run the tests with coverage first")
    report = json.loads(path.read_text(encoding="utf-8"))
    total = Decimal(str(report["totals"]["percent_covered"])).quantize(Decimal("0.1"))
    modules = tuple(
        ModuleCoverage(
            path=name,
            covered=summary["summary"]["covered_lines"],
            statements=summary["summary"]["num_statements"],
        )
        for name, summary in sorted(report["files"].items())
    )
    return total, modules


def under_floor(
    modules: tuple[ModuleCoverage, ...], floor: Decimal = MODULE_FLOOR
) -> tuple[ModuleCoverage, ...]:
    return tuple(item for item in modules if item.is_under(floor))


def main(argv: list[str] | None = None) -> int:
    arguments = sys.argv[1:] if argv is None else argv
    path = Path(arguments[0]) if arguments else REPORT
    try:
        total, modules = read_report(path)
    except FileNotFoundError as exc:
        print(f"coverage: {exc}")
        return 1
    print(f"coverage: {total} percent over {len(modules)} modules")
    failed = False
    if total < PACKAGE_FLOOR:
        print(f"coverage: the package is under the {PACKAGE_FLOOR} percent floor")
        failed = True
    for module in under_floor(modules):
        print(f"coverage: {module.path} is at {module.percent} percent")
        failed = True
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
