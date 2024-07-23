"""The season report the board reads in November.

It answers four questions and nothing else. How much came through the headgate,
how much reached the turnouts, how much of that is actually proved, and where
the difference went. The fourth is the one that starts arguments, so the report
separates the loss the ditch was always going to take from the loss nobody can
account for.

The report builds rows rather than text. What it knows about is water; how wide
a column should be is the command line's business.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from ..carriage.apportion import Apportionment, expected_loss, measured_loss
from ..errors import PolicyError
from ..ids import TurnoutCode
from ..measure.delivery import DeliveryLedger
from ..model.ditch import DitchSystem
from ..units import round_volume


@dataclass(frozen=True, slots=True)
class TurnoutLine:
    """One turnout's line on the report."""

    turnout: TurnoutCode
    delivered_af: Decimal
    measured_af: Decimal
    estimated_af: Decimal
    loss_af: Decimal
    unaccounted_hours: Decimal

    @property
    def charged_af(self) -> Decimal:
        return round_volume(self.delivered_af + self.loss_af)

    @property
    def is_proved(self) -> bool:
        return self.estimated_af == 0 and self.unaccounted_hours == 0


@dataclass(frozen=True, slots=True)
class SeasonReport:
    """The whole season, in the order the board asks about it."""

    water_year: int
    district: str
    headgate_af: Decimal
    lines: tuple[TurnoutLine, ...]
    expected_loss_af: Decimal

    @property
    def delivered_af(self) -> Decimal:
        return round_volume(sum((line.delivered_af for line in self.lines), Decimal("0")))

    @property
    def measured_af(self) -> Decimal:
        return round_volume(sum((line.measured_af for line in self.lines), Decimal("0")))

    @property
    def estimated_af(self) -> Decimal:
        return round_volume(sum((line.estimated_af for line in self.lines), Decimal("0")))

    @property
    def loss_af(self) -> Decimal:
        return round_volume(self.headgate_af - self.delivered_af)

    @property
    def unexplained_loss_af(self) -> Decimal:
        return round_volume(self.loss_af - self.expected_loss_af)

    @property
    def carriage_efficiency(self) -> Decimal:
        if self.headgate_af == 0:
            return Decimal("0")
        return (self.delivered_af / self.headgate_af).quantize(Decimal("0.001"))

    @property
    def proved_share(self) -> Decimal:
        if self.delivered_af == 0:
            return Decimal("0")
        return (self.measured_af / self.delivered_af).quantize(Decimal("0.001"))

    @property
    def unproved_turnouts(self) -> tuple[TurnoutCode, ...]:
        return tuple(line.turnout for line in self.lines if not line.is_proved)

    def line_for(self, turnout: TurnoutCode) -> TurnoutLine:
        for line in self.lines:
            if line.turnout == turnout:
                return line
        raise PolicyError(f"turnout {turnout} is not on the {self.water_year} report")

    def rows(self) -> list[list[str]]:
        """One row a turnout, for whatever is going to print it."""

        return [
            [
                str(line.turnout),
                f"{line.delivered_af:.2f}",
                f"{line.measured_af:.2f}",
                f"{line.estimated_af:.2f}",
                f"{line.loss_af:.2f}",
                f"{line.charged_af:.2f}",
                f"{line.unaccounted_hours:.1f}",
            ]
            for line in self.lines
        ]

    def summary(self) -> list[tuple[str, str]]:
        """The block that goes at the top of the printed report."""

        return [
            ("district", self.district),
            ("water year", str(self.water_year)),
            ("headgate", f"{self.headgate_af:.2f} acre feet"),
            ("delivered", f"{self.delivered_af:.2f} acre feet"),
            ("ditch loss", f"{self.loss_af:.2f} acre feet"),
            ("expected loss", f"{self.expected_loss_af:.2f} acre feet"),
            ("unexplained", f"{self.unexplained_loss_af:.2f} acre feet"),
            ("carriage", f"{self.carriage_efficiency:.3f}"),
            ("proved", f"{self.proved_share:.3f} of what was delivered"),
        ]


def build(
    water_year: int,
    district: str,
    ledger: DeliveryLedger,
    apportionment: Apportionment,
    headgate_af: Decimal,
    system: DitchSystem,
) -> SeasonReport:
    """Put the season report together from the ledger and the loss split."""

    volumes = ledger.volumes()
    measured_loss(headgate_af, volumes)
    charged = {item.turnout: item.loss_af for item in apportionment.charges}
    missing = [turnout for turnout in volumes if turnout not in charged]
    if missing:
        raise PolicyError(f"turnout {missing[0]} took water and was charged no loss")
    lines = tuple(
        TurnoutLine(
            turnout=record.turnout,
            delivered_af=record.total_af,
            measured_af=record.measured_af,
            estimated_af=record.estimated_af,
            loss_af=charged[record.turnout],
            unaccounted_hours=record.unaccounted_hours,
        )
        for record in sorted(ledger.records, key=lambda item: str(item.turnout))
    )
    return SeasonReport(
        water_year=water_year,
        district=district,
        headgate_af=round_volume(headgate_af),
        lines=lines,
        expected_loss_af=expected_loss(system, volumes),
    )
