"""Restating a season that was billed off the wrong numbers.

It happens most years. A weir is checked in September, the check says the staff
had been reading two hundredths high since spring, and every delivery through
that turnout was over stated. The volumes change, the volumes decide the band,
the band decides the bill.

A bill is never edited. The original stands, a reversal of it is issued, and a
replacement is issued beside it, so the three of them sit in the file and the
arithmetic is visible. That is the only way an auditor can follow what happened
and the only way a shareholder who paid the first bill can see his credit.

A restatement over the board's threshold does not go out on the clerk's say so.
It goes on the agenda.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from ..errors import PolicyError, ValidationError
from ..money import Money
from .billing import Bill, ChargeKind, Line

BOARD_APPROVAL_THRESHOLD = Money.from_dollars("250.00")


def reverse(bill: Bill, reposted_on: date, reason: str) -> Bill:
    """A bill that cancels another one out, line for line.

    A reversed charge is a credit and a reversed credit is a charge again, so
    the kind of each line flips with its sign rather than being carried over.
    """

    if not reason.strip():
        raise ValidationError("a reversal says why it was made")
    if not bill.lines:
        raise PolicyError(f"the {bill.water_year} bill for {bill.account} has nothing to reverse")
    lines: list[Line] = []
    for line in bill.lines:
        amount = -line.amount
        kind = ChargeKind.CREDIT if amount.cents <= 0 else ChargeKind.PENALTY
        lines.append(
            Line(
                kind=kind,
                description=f"reversal: {line.description}",
                quantity=-line.quantity,
                amount=amount,
            )
        )
    return Bill(
        account=bill.account,
        water_year=bill.water_year,
        issued_on=reposted_on,
        lines=tuple(lines),
    )


@dataclass(frozen=True, slots=True)
class Restatement:
    """The three bills a repost leaves in the file."""

    original: Bill
    reversal: Bill
    replacement: Bill
    reason: str
    reposted_on: date

    def __post_init__(self) -> None:
        if self.original.account != self.replacement.account:
            raise PolicyError("a restatement cannot move a bill to another account")
        if self.original.water_year != self.replacement.water_year:
            raise PolicyError("a restatement cannot move a bill to another season")
        if not self.reason.strip():
            raise ValidationError("a restatement says why it was made")

    @property
    def adjustment(self) -> Money:
        return self.replacement.total - self.original.total

    @property
    def net_owed(self) -> Money:
        return self.reversal.total + self.replacement.total

    @property
    def is_a_credit(self) -> bool:
        return self.adjustment.cents < 0

    @property
    def needs_board_approval(self) -> bool:
        size = abs(self.adjustment.cents)
        return size > BOARD_APPROVAL_THRESHOLD.cents

    def describe(self) -> str:
        direction = "credit" if self.is_a_credit else "further charge"
        return (
            f"{self.original.water_year} bill for account {self.original.account} restated on "
            f"{self.reposted_on}: {direction} of {abs(self.adjustment.cents) / 100:.2f}, "
            f"{self.reason}"
        )


def restate(
    original: Bill, replacement: Bill, reason: str, reposted_on: date, board_approved: bool = False
) -> Restatement:
    """Reverse a bill and issue its replacement, both dated the same day."""

    restatement = Restatement(
        original=original,
        reversal=reverse(original, reposted_on, reason),
        replacement=replacement,
        reason=reason,
        reposted_on=reposted_on,
    )
    if restatement.needs_board_approval and not board_approved:
        raise PolicyError(
            f"a restatement of {abs(restatement.adjustment.cents) / 100:.2f} is over the "
            f"{BOARD_APPROVAL_THRESHOLD} threshold and needs the board"
        )
    return restatement


def volume_moved(original_af: Decimal, corrected_af: Decimal) -> Decimal:
    """How much the delivery record moved, which is what started all this."""

    return (corrected_af - original_af).quantize(Decimal("0.0001"))
