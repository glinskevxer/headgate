"""Money, for the annual assessment and nothing else.

Assessments are billed per share and then apportioned, and an apportionment
that loses a cent is a complaint at the next board meeting. Money is whole
cents in an int, and every split is a largest remainder split so the pieces
add back to the whole.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from typing import Self

from .errors import ValidationError

CENTS_PER_DOLLAR = Decimal("100")


@dataclass(frozen=True, slots=True, order=True)
class Money:
    """An amount in whole cents. Negative amounts are credits."""

    cents: int

    @classmethod
    def zero(cls) -> Self:
        return cls(0)

    @classmethod
    def from_dollars(cls, dollars: Decimal | str | int) -> Self:
        amount = Decimal(dollars) if not isinstance(dollars, Decimal) else dollars
        scaled = (amount * CENTS_PER_DOLLAR).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
        return cls(int(scaled))

    @classmethod
    def parse(cls, text: str) -> Self:
        cleaned = text.strip().replace("$", "").replace(",", "")
        if not cleaned:
            raise ValidationError("an empty string is not an amount")
        try:
            return cls.from_dollars(Decimal(cleaned))
        except ArithmeticError as exc:
            raise ValidationError(f"{text!r} is not an amount") from exc

    @property
    def dollars(self) -> Decimal:
        return (Decimal(self.cents) / CENTS_PER_DOLLAR).quantize(Decimal("0.01"))

    def __str__(self) -> str:
        sign = "-" if self.cents < 0 else ""
        whole, part = divmod(abs(self.cents), 100)
        return f"{sign}${whole:,}.{part:02d}"

    def __add__(self, other: Money) -> Money:
        return Money(self.cents + other.cents)

    def __sub__(self, other: Money) -> Money:
        return Money(self.cents - other.cents)

    def __neg__(self) -> Money:
        return Money(-self.cents)

    def times(self, factor: Decimal) -> Money:
        scaled = (Decimal(self.cents) * factor).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
        return Money(int(scaled))

    def allocate(self, weights: list[Decimal]) -> list[Money]:
        """Split an amount by weight so the pieces add back to the whole."""

        if not weights:
            raise ValidationError("nothing to allocate an amount across")
        if any(weight < 0 for weight in weights):
            raise ValidationError("an allocation weight may not be negative")
        total = sum(weights, Decimal("0"))
        if total <= 0:
            raise ValidationError("an allocation needs at least one positive weight")
        raw = [Decimal(self.cents) * weight / total for weight in weights]
        floors = [int(value.to_integral_value(rounding="ROUND_FLOOR")) for value in raw]
        remainder = self.cents - sum(floors)
        order = sorted(range(len(raw)), key=lambda i: raw[i] - floors[i], reverse=True)
        pieces = list(floors)
        step = 1 if remainder >= 0 else -1
        for index in range(abs(remainder)):
            pieces[order[index % len(order)]] += step
        return [Money(value) for value in pieces]
