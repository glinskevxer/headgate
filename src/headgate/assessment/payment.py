"""Payments, delinquency, and the point at which the water goes off.

Money comes in against the oldest bill first, whatever the shareholder writes
on the cheque. That is the rule every ditch company uses and it is the only one
that keeps a running balance meaning anything.

Past the due date an unpaid balance carries a penalty by the month, and past
the district's patience the account is delinquent, which is not a bookkeeping
state. A delinquent account does not take delivery, which is enforced back in
the order intake, so an unpaid assessment turns into a dry field in about the
time it takes the office to run the list.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from enum import Enum

from ..errors import PolicyError, ValidationError
from ..ids import AccountNumber
from ..money import Money
from .billing import Bill

DEFAULT_PENALTY_RATE = Decimal("0.01")
DEFAULT_GRACE_DAYS = 30
DEFAULT_SHUTOFF_DAYS = 90


class PaymentMethod(Enum):
    """How the money arrived."""

    CHEQUE = "cheque"
    CASH = "cash"
    TRANSFER = "transfer"
    WRITE_OFF = "write_off"

    @property
    def is_money(self) -> bool:
        return self is not PaymentMethod.WRITE_OFF


@dataclass(frozen=True, slots=True)
class Payment:
    """One payment against one account."""

    account: AccountNumber
    received_on: date
    amount: Money
    method: PaymentMethod = PaymentMethod.CHEQUE
    reference: str = ""

    def __post_init__(self) -> None:
        if self.amount.cents <= 0:
            raise ValidationError(
                f"a payment of {self.amount} from account {self.account} is not a payment"
            )


@dataclass(frozen=True, slots=True)
class Applied:
    """How much of a payment landed on one bill."""

    water_year: int
    amount: Money


@dataclass(frozen=True, slots=True)
class AccountLedger:
    """One account's bills and payments, in the order they happened."""

    account: AccountNumber
    bills: tuple[Bill, ...]
    payments: tuple[Payment, ...] = ()

    def __post_init__(self) -> None:
        for bill in self.bills:
            if bill.account != self.account:
                raise ValidationError(
                    f"a bill for {bill.account} turned up on account {self.account}"
                )
        for payment in self.payments:
            if payment.account != self.account:
                raise ValidationError(
                    f"a payment from {payment.account} turned up on account {self.account}"
                )

    @property
    def billed(self) -> Money:
        total = Money.zero()
        for bill in self.bills:
            total = total + bill.total
        return total

    @property
    def paid(self) -> Money:
        total = Money.zero()
        for payment in self.payments:
            total = total + payment.amount
        return total

    @property
    def balance(self) -> Money:
        return self.billed - self.paid

    @property
    def is_clear(self) -> bool:
        return self.balance.cents <= 0

    def paid_by(self, day: date) -> Money:
        total = Money.zero()
        for payment in self.payments:
            if payment.received_on <= day:
                total = total + payment.amount
        return total

    def balance_on(self, day: date) -> Money:
        billed = Money.zero()
        for bill in self.bills:
            if bill.issued_on <= day:
                billed = billed + bill.total
        return billed - self.paid_by(day)

    def apply(self) -> tuple[Applied, ...]:
        """Spread what has been paid over the bills, oldest first."""

        left = self.paid
        landed: list[Applied] = []
        for bill in sorted(self.bills, key=lambda item: (item.issued_on, item.water_year)):
            if bill.total.cents <= 0:
                continue
            taken = bill.total if left >= bill.total else left
            if taken.cents <= 0:
                break
            landed.append(Applied(water_year=bill.water_year, amount=taken))
            left = left - taken
        return tuple(landed)

    def unpaid_years(self) -> tuple[int, ...]:
        settled = {item.water_year for item in self.apply() if item.amount.cents > 0}
        fully = set()
        for item in self.apply():
            for bill in self.bills:
                if bill.water_year == item.water_year and item.amount == bill.total:
                    fully.add(item.water_year)
        return tuple(
            sorted(
                bill.water_year
                for bill in self.bills
                if bill.total.cents > 0
                and (bill.water_year not in settled or bill.water_year not in fully)
            )
        )

    def days_late(self, due_on: date, as_of: date) -> int:
        if as_of < due_on:
            return 0
        if self.balance_on(as_of).cents <= 0:
            return 0
        return (as_of - due_on).days

    def penalty(
        self,
        due_on: date,
        as_of: date,
        monthly_rate: Decimal = DEFAULT_PENALTY_RATE,
        grace_days: int = DEFAULT_GRACE_DAYS,
    ) -> Money:
        """What the unpaid balance has cost in penalty by a day."""

        if monthly_rate < 0:
            raise ValidationError("a penalty rate may not be negative")
        late = self.days_late(due_on, as_of)
        if late <= grace_days:
            return Money.zero()
        months = Decimal(late - grace_days) / Decimal("30")
        whole_months = months.quantize(Decimal("1"), rounding=ROUND_HALF_UP)
        if whole_months <= 0:
            return Money.zero()
        return self.balance_on(as_of).times(monthly_rate * whole_months)

    def is_delinquent(
        self, due_on: date, as_of: date, grace_days: int = DEFAULT_GRACE_DAYS
    ) -> bool:
        return self.days_late(due_on, as_of) > grace_days

    def is_shut_off(
        self, due_on: date, as_of: date, shutoff_days: int = DEFAULT_SHUTOFF_DAYS
    ) -> bool:
        """Past this the water goes off, which the order intake enforces."""

        return self.days_late(due_on, as_of) > shutoff_days

    def with_payment(self, payment: Payment) -> AccountLedger:
        if payment.account != self.account:
            raise PolicyError(
                f"a payment from {payment.account} cannot land on account {self.account}"
            )
        return AccountLedger(
            account=self.account,
            bills=self.bills,
            payments=(*self.payments, payment),
        )
