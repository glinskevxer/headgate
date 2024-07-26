"""The water commissioner's day.

One page a day through the summer: what the creek was carrying, what every
right was entitled to take after the calls that are standing, and what it
actually took. The last column is the only one anybody argues with.

A right over its allowance is not the same as a right over its decree. A junior
under a curtailment notice may be well inside its decreed rate and still be
taking water it has been told to leave alone, and the report has to say which
of the two happened.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal

from ..errors import PolicyError
from ..ids import DecreeNumber
from ..model.right import WaterRight, order_by_priority
from ..priority.curtail import CurtailmentRegister
from ..units import round_rate


@dataclass(frozen=True, slots=True)
class DiversionLine:
    """One right, on one day."""

    decree: DecreeNumber
    owner: str
    decreed_cfs: Decimal
    allowed_cfs: Decimal
    taking_cfs: Decimal
    curtailed: bool

    @property
    def over_cfs(self) -> Decimal:
        over = self.taking_cfs - self.allowed_cfs
        return round_rate(over) if over > 0 else Decimal("0")

    @property
    def is_over(self) -> bool:
        return self.over_cfs > 0

    @property
    def over_its_decree(self) -> bool:
        return self.taking_cfs > self.decreed_cfs

    @property
    def unused_cfs(self) -> Decimal:
        unused = self.allowed_cfs - self.taking_cfs
        return round_rate(unused) if unused > 0 else Decimal("0")


@dataclass(frozen=True, slots=True)
class DayReport:
    """The whole stream for one day."""

    day: date
    stream_flow_cfs: Decimal
    lines: tuple[DiversionLine, ...]

    @property
    def diverted_cfs(self) -> Decimal:
        return round_rate(sum((line.taking_cfs for line in self.lines), Decimal("0")))

    @property
    def allowed_cfs(self) -> Decimal:
        return round_rate(sum((line.allowed_cfs for line in self.lines), Decimal("0")))

    @property
    def passing_cfs(self) -> Decimal:
        """What ran on down the creek past everybody."""

        left = self.stream_flow_cfs - self.diverted_cfs
        return round_rate(left) if left > 0 else Decimal("0")

    @property
    def over_diverting(self) -> tuple[DiversionLine, ...]:
        return tuple(line for line in self.lines if line.is_over)

    @property
    def curtailed(self) -> tuple[DiversionLine, ...]:
        return tuple(line for line in self.lines if line.curtailed)

    @property
    def in_compliance(self) -> bool:
        return not self.over_diverting

    @property
    def oversubscribed(self) -> bool:
        """More was diverted than the creek was carrying, which happens."""

        return self.diverted_cfs > self.stream_flow_cfs

    def line_for(self, decree: DecreeNumber) -> DiversionLine:
        for line in self.lines:
            if line.decree == decree:
                return line
        raise PolicyError(f"decree {decree} is not on the report for {self.day}")

    def rows(self) -> list[list[str]]:
        return [
            [
                str(line.decree),
                line.owner,
                f"{line.decreed_cfs:.3f}",
                f"{line.allowed_cfs:.3f}",
                f"{line.taking_cfs:.3f}",
                f"{line.over_cfs:.3f}",
                "yes" if line.curtailed else "no",
            ]
            for line in self.lines
        ]

    def summary(self) -> list[tuple[str, str]]:
        return [
            ("day", self.day.isoformat()),
            ("creek", f"{self.stream_flow_cfs:.3f} cfs"),
            ("diverted", f"{self.diverted_cfs:.3f} cfs"),
            ("passing", f"{self.passing_cfs:.3f} cfs"),
            ("over", f"{len(self.over_diverting)} rights"),
            ("curtailed", f"{len(self.curtailed)} rights"),
        ]


def build_day(
    day: date,
    rights: list[WaterRight],
    diverting: dict[DecreeNumber, Decimal],
    register: CurtailmentRegister,
    stream_flow_cfs: Decimal,
    at: datetime | None = None,
) -> DayReport:
    """Put one day's page together, most senior right first."""

    if stream_flow_cfs < 0:
        raise PolicyError("a creek cannot run backwards")
    moment = at if at is not None else datetime.combine(day, datetime.min.time())
    lines: list[DiversionLine] = []
    for right in order_by_priority([item for item in rights if item.is_active]):
        decreed = right.rate_or_zero()
        held_to = register.allowed_rate(right.decree, moment)
        allowed = decreed if held_to is None else min(decreed, held_to)
        lines.append(
            DiversionLine(
                decree=right.decree,
                owner=right.owner,
                decreed_cfs=round_rate(decreed),
                allowed_cfs=round_rate(allowed),
                taking_cfs=round_rate(diverting.get(right.decree, Decimal("0"))),
                curtailed=held_to is not None,
            )
        )
    return DayReport(day=day, stream_flow_cfs=round_rate(stream_flow_cfs), lines=tuple(lines))
