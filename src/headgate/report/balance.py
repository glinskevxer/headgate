"""The water balance, month by month.

A season total hides the month everything went wrong. This cuts the same
numbers into calendar months: what came through the headgate, what the turnouts
took, what the loss rates say the ditch should have kept, and what is left over
that nobody can account for.

The last column is the one worth reading. A district that loses eight percent
every month is a ditch with a known leak. A district that loses eight percent
in May and twenty two in July has something that started in July: a break, a
gate somebody left open, or a turnout that stopped being measured.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from ..errors import PolicyError
from ..measure.delivery import DeliveryLedger
from ..measure.integrate import IntegratedVolume
from ..units import round_volume


@dataclass(frozen=True, slots=True)
class MonthBalance:
    """One month of the season, from the headgate to the fields."""

    month: int
    headgate_af: Decimal
    delivered_af: Decimal
    expected_loss_af: Decimal

    @property
    def loss_af(self) -> Decimal:
        return round_volume(self.headgate_af - self.delivered_af)

    @property
    def unexplained_af(self) -> Decimal:
        return round_volume(self.loss_af - self.expected_loss_af)

    @property
    def carriage(self) -> Decimal:
        if self.headgate_af <= 0:
            return Decimal("0")
        return (self.delivered_af / self.headgate_af).quantize(Decimal("0.001"))

    @property
    def is_out_of_balance(self) -> bool:
        """Whether the month lost materially more than the rates account for."""

        if self.headgate_af <= 0:
            return False
        return self.unexplained_af > self.headgate_af * Decimal("0.05")


@dataclass(frozen=True, slots=True)
class Balance:
    """The season, month by month."""

    water_year: int
    months: tuple[MonthBalance, ...]

    @property
    def headgate_af(self) -> Decimal:
        return round_volume(sum((item.headgate_af for item in self.months), Decimal("0")))

    @property
    def delivered_af(self) -> Decimal:
        return round_volume(sum((item.delivered_af for item in self.months), Decimal("0")))

    @property
    def unexplained_af(self) -> Decimal:
        return round_volume(sum((item.unexplained_af for item in self.months), Decimal("0")))

    @property
    def out_of_balance(self) -> tuple[MonthBalance, ...]:
        return tuple(item for item in self.months if item.is_out_of_balance)

    @property
    def worst_month(self) -> MonthBalance | None:
        if not self.months:
            return None
        return max(self.months, key=lambda item: item.unexplained_af)

    def month(self, number: int) -> MonthBalance:
        for item in self.months:
            if item.month == number:
                return item
        raise PolicyError(f"month {number} is not in this balance")

    def rows(self) -> list[list[str]]:
        return [
            [
                str(item.month),
                f"{item.headgate_af:.2f}",
                f"{item.delivered_af:.2f}",
                f"{item.loss_af:.2f}",
                f"{item.expected_loss_af:.2f}",
                f"{item.unexplained_af:.2f}",
                f"{item.carriage}",
            ]
            for item in self.months
        ]

    def summary(self) -> list[tuple[str, str]]:
        worst = self.worst_month
        return [
            ("water year", str(self.water_year)),
            ("headgate", f"{self.headgate_af:.2f} acre feet"),
            ("delivered", f"{self.delivered_af:.2f} acre feet"),
            ("unexplained", f"{self.unexplained_af:.2f} acre feet"),
            ("months out", str(len(self.out_of_balance))),
            ("worst month", str(worst.month) if worst is not None else "none"),
        ]


def _by_month(volume: IntegratedVolume) -> dict[int, Decimal]:
    found: dict[int, Decimal] = {}
    for segment in volume.segments:
        for piece in segment.span.split_on_days():
            share = piece.seconds / segment.span.seconds if segment.span.seconds else Decimal("0")
            month = piece.start.month
            found[month] = found.get(month, Decimal("0")) + segment.volume_af * share
    return {month: round_volume(value) for month, value in sorted(found.items())}


def build(
    water_year: int,
    headgate: IntegratedVolume,
    ledger: DeliveryLedger,
    expected_loss_fraction: Decimal,
) -> Balance:
    """Cut a season into months, from the headgate down to the fields."""

    if expected_loss_fraction < 0 or expected_loss_fraction >= 1:
        raise PolicyError(
            f"{expected_loss_fraction} is not a share of the headgate the ditch keeps"
        )
    turned_in = _by_month(headgate)
    delivered: dict[int, Decimal] = {}
    for record in ledger.records:
        for month, value in _by_month(record.volume).items():
            delivered[month] = delivered.get(month, Decimal("0")) + value
    months = sorted(set(turned_in) | set(delivered))
    return Balance(
        water_year=water_year,
        months=tuple(
            MonthBalance(
                month=month,
                headgate_af=turned_in.get(month, Decimal("0")),
                delivered_af=round_volume(delivered.get(month, Decimal("0"))),
                expected_loss_af=round_volume(
                    turned_in.get(month, Decimal("0")) * expected_loss_fraction
                ),
            )
            for month in months
        ),
    )
