"""Building the bills at the end of a season.

A bill is a list of lines and nothing else. Every charge on it says what it was
for and how much water or how many shares it was worth, because the first thing
a shareholder does with a bill he disagrees with is ask which line is wrong.

The ditch loss that was charged out to his turnout is billed at the same rate
as the water he took, and it goes on its own line. Charging it silently inside
the delivery is how a district ends up explaining itself at an annual meeting.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from enum import Enum

from ..errors import PolicyError, ValidationError
from ..ids import AccountNumber
from ..money import Money
from ..units import round_volume
from .tiers import RateSchedule

NOTHING = Money(0)


class ChargeKind(Enum):
    """What a line on a bill is for."""

    SHARES = "shares"
    WATER = "water"
    DITCH_LOSS = "ditch_loss"
    PENALTY = "penalty"
    CREDIT = "credit"

    @property
    def is_credit(self) -> bool:
        return self is ChargeKind.CREDIT


@dataclass(frozen=True, slots=True)
class Line:
    """One charge, with what it was measured against."""

    kind: ChargeKind
    description: str
    quantity: Decimal
    amount: Money

    def __post_init__(self) -> None:
        if self.kind.is_credit and self.amount.cents > 0:
            raise ValidationError("a credit that adds to the bill is not a credit")
        if not self.kind.is_credit and self.amount.cents < 0:
            raise ValidationError(f"a {self.kind.value} charge may not be negative")


@dataclass(frozen=True, slots=True)
class Bill:
    """What one account owes for one season."""

    account: AccountNumber
    water_year: int
    issued_on: date
    lines: tuple[Line, ...]

    @property
    def total(self) -> Money:
        total = Money.zero()
        for line in self.lines:
            total = total + line.amount
        return total

    @property
    def charges(self) -> Money:
        total = Money.zero()
        for line in self.lines:
            if not line.kind.is_credit:
                total = total + line.amount
        return total

    @property
    def credits(self) -> Money:
        total = Money.zero()
        for line in self.lines:
            if line.kind.is_credit:
                total = total + line.amount
        return total

    @property
    def in_credit(self) -> bool:
        return self.total.cents < 0

    def line_for(self, kind: ChargeKind) -> Line | None:
        for line in self.lines:
            if line.kind is kind:
                return line
        return None


def bill_account(
    account: AccountNumber,
    water_year: int,
    issued_on: date,
    schedule: RateSchedule,
    shares: Decimal,
    delivered_af: Decimal,
    loss_af: Decimal = Decimal("0"),
    credit: Money = NOTHING,
    penalty: Money = NOTHING,
) -> Bill:
    """Build one bill from a season's shares, deliveries and charged loss."""

    if schedule.water_year != water_year:
        raise PolicyError(f"the {schedule.water_year} schedule cannot bill the {water_year} season")
    if delivered_af < 0 or loss_af < 0:
        raise ValidationError("a bill cannot be built from negative water")
    lines: list[Line] = [
        Line(
            ChargeKind.SHARES,
            f"{shares} shares at {schedule.per_share} a share",
            shares,
            schedule.share_charge(shares),
        )
    ]
    if delivered_af > 0:
        lines.append(
            Line(
                ChargeKind.WATER,
                f"{round_volume(delivered_af)} acre feet delivered",
                round_volume(delivered_af),
                schedule.water_charge(delivered_af),
            )
        )
    if loss_af > 0:
        charged = schedule.water_charge(delivered_af + loss_af) - schedule.water_charge(
            delivered_af
        )
        lines.append(
            Line(
                ChargeKind.DITCH_LOSS,
                f"{round_volume(loss_af)} acre feet of ditch loss",
                round_volume(loss_af),
                charged,
            )
        )
    if penalty.cents > 0:
        lines.append(Line(ChargeKind.PENALTY, "late payment penalty", Decimal("0"), penalty))
    if credit.cents != 0:
        amount = credit if credit.cents < 0 else -credit
        lines.append(Line(ChargeKind.CREDIT, "credit carried forward", Decimal("0"), amount))
    return Bill(account=account, water_year=water_year, issued_on=issued_on, lines=tuple(lines))


@dataclass(frozen=True, slots=True)
class BillRun:
    """Every bill for a season, as one run."""

    water_year: int
    issued_on: date
    bills: tuple[Bill, ...]

    def __post_init__(self) -> None:
        seen: set[AccountNumber] = set()
        for bill in self.bills:
            if bill.account in seen:
                raise ValidationError(f"account {bill.account} is billed twice in one run")
            if bill.water_year != self.water_year:
                raise ValidationError(
                    f"a {bill.water_year} bill turned up in the {self.water_year} run"
                )
            seen.add(bill.account)

    @property
    def total(self) -> Money:
        total = Money.zero()
        for bill in self.bills:
            total = total + bill.total
        return total

    @property
    def accounts(self) -> tuple[AccountNumber, ...]:
        return tuple(sorted(bill.account for bill in self.bills))

    def bill_for(self, account: AccountNumber) -> Bill:
        for bill in self.bills:
            if bill.account == account:
                return bill
        raise PolicyError(f"account {account} was not in the {self.water_year} run")

    @property
    def in_credit(self) -> tuple[Bill, ...]:
        return tuple(bill for bill in self.bills if bill.in_credit)
