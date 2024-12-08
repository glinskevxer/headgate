"""The statement that goes out with the bill.

One page for one account: what it holds, what it took, what it owes and what
happens if it does not pay. Everything on it comes from somewhere else in the
system, which is the point. The statement is where a shareholder finds out that
his July water was only estimated, and it is the only document that puts the
water and the money on the same sheet of paper.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from ..assessment.payment import AccountLedger
from ..errors import PolicyError
from ..ids import AccountNumber, TurnoutCode
from ..measure.delivery import DeliveryLedger
from ..money import Money
from ..units import round_volume


@dataclass(frozen=True, slots=True)
class DeliveryLine:
    """One turnout's water on the statement."""

    turnout: TurnoutCode
    delivered_af: Decimal
    measured_af: Decimal
    loss_af: Decimal

    @property
    def estimated_af(self) -> Decimal:
        return round_volume(self.delivered_af - self.measured_af)

    @property
    def charged_af(self) -> Decimal:
        return round_volume(self.delivered_af + self.loss_af)

    @property
    def is_proved(self) -> bool:
        return self.estimated_af == 0


@dataclass(frozen=True, slots=True)
class Statement:
    """What one account is being told."""

    account: AccountNumber
    name: str
    water_year: int
    shares: Decimal
    lines: tuple[DeliveryLine, ...]
    ledger: AccountLedger
    due_on: date
    as_of: date

    @property
    def delivered_af(self) -> Decimal:
        return round_volume(sum((line.delivered_af for line in self.lines), Decimal("0")))

    @property
    def loss_af(self) -> Decimal:
        return round_volume(sum((line.loss_af for line in self.lines), Decimal("0")))

    @property
    def charged_af(self) -> Decimal:
        return round_volume(self.delivered_af + self.loss_af)

    @property
    def estimated_af(self) -> Decimal:
        return round_volume(sum((line.estimated_af for line in self.lines), Decimal("0")))

    @property
    def balance(self) -> Money:
        return self.ledger.balance_on(self.as_of)

    @property
    def penalty(self) -> Money:
        return self.ledger.penalty(self.due_on, self.as_of)

    @property
    def owed(self) -> Money:
        return self.balance + self.penalty

    @property
    def is_delinquent(self) -> bool:
        return self.ledger.is_delinquent(self.due_on, self.as_of)

    @property
    def is_shut_off(self) -> bool:
        return self.ledger.is_shut_off(self.due_on, self.as_of)

    @property
    def unproved_turnouts(self) -> tuple[TurnoutCode, ...]:
        return tuple(line.turnout for line in self.lines if not line.is_proved)

    def line_for(self, turnout: TurnoutCode) -> DeliveryLine:
        for line in self.lines:
            if line.turnout == turnout:
                return line
        raise PolicyError(f"turnout {turnout} is not on this statement")

    def rows(self) -> list[list[str]]:
        return [
            [
                str(line.turnout),
                f"{line.delivered_af:.2f}",
                f"{line.measured_af:.2f}",
                f"{line.estimated_af:.2f}",
                f"{line.loss_af:.2f}",
                f"{line.charged_af:.2f}",
            ]
            for line in self.lines
        ]

    def summary(self) -> list[tuple[str, str]]:
        standing = (
            "shut off"
            if self.is_shut_off
            else ("delinquent" if self.is_delinquent else "in good standing")
        )
        return [
            ("account", f"{self.account}  {self.name}"),
            ("water year", str(self.water_year)),
            ("shares", f"{self.shares}"),
            ("delivered", f"{self.delivered_af:.2f} acre feet"),
            ("ditch loss", f"{self.loss_af:.2f} acre feet"),
            ("charged for", f"{self.charged_af:.2f} acre feet"),
            ("estimated", f"{self.estimated_af:.2f} acre feet"),
            ("billed", str(self.ledger.billed)),
            ("paid", str(self.ledger.paid)),
            ("balance", str(self.balance)),
            ("penalty", str(self.penalty)),
            ("owed", str(self.owed)),
            ("standing", standing),
        ]


def build(
    account: AccountNumber,
    name: str,
    water_year: int,
    shares: Decimal,
    ledger: AccountLedger,
    deliveries: DeliveryLedger,
    turnouts: tuple[TurnoutCode, ...],
    charged_loss: dict[TurnoutCode, Decimal],
    due_on: date,
    as_of: date,
) -> Statement:
    """Put one account's statement together for a season."""

    if ledger.account != account:
        raise PolicyError(f"the ledger for {ledger.account} cannot go on a statement for {account}")
    lines: list[DeliveryLine] = []
    for turnout in sorted(turnouts, key=str):
        record = deliveries.for_turnout(turnout)
        lines.append(
            DeliveryLine(
                turnout=turnout,
                delivered_af=record.total_af,
                measured_af=record.measured_af,
                loss_af=charged_loss.get(turnout, Decimal("0")),
            )
        )
    return Statement(
        account=account,
        name=name,
        water_year=water_year,
        shares=shares,
        lines=tuple(lines),
        ledger=ledger,
        due_on=due_on,
        as_of=as_of,
    )
