"""Weir ratings.

Three weirs turn up in this system. A Cipolletti has trapezoidal ends cut one
horizontal to four vertical, which pays back the end contraction and leaves a
plain power law. A rectangular weir either runs the full width of the box, in
which case it behaves the same way, or it is contracted, in which case the
effective crest shortens as the head rises and the rating stops being a power
law at all. A ninety degree V notch is a steeper curve and is what gets put in
where the flow is small.

The head limits are not preferences. A weir stops behaving like a weir when the
head gets past a third of the crest, so a wide structure gets a wider working
range and a narrow one does not, and a reading past that limit is out of range
however carefully somebody read the staff.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from ..errors import HeadOutOfRangeError, ValidationError
from ..units import round_rate
from .curve import PowerCurve

CIPOLLETTI_COEFFICIENT = Decimal("3.367")
FRANCIS_COEFFICIENT = Decimal("3.33")
V_NOTCH_90_COEFFICIENT = Decimal("2.49")
V_NOTCH_90_EXPONENT = Decimal("2.48")

WEIR_EXPONENT = Decimal("1.5")
MINIMUM_HEAD_FEET = Decimal("0.2")
HEAD_TO_CREST_LIMIT = Decimal("3")
CONTRACTION_PER_HEAD = Decimal("0.2")


def _crest_limit(crest_width_feet: Decimal) -> Decimal:
    return (crest_width_feet / HEAD_TO_CREST_LIMIT).quantize(Decimal("0.001"))


def _check_crest(crest_width_feet: Decimal) -> None:
    if crest_width_feet <= 0:
        raise ValidationError(f"a weir crest of {crest_width_feet} feet is not a weir")


def cipolletti(crest_width_feet: Decimal, head_offset_feet: Decimal = Decimal("0")) -> PowerCurve:
    """The rating for a Cipolletti weir of a given crest width."""

    _check_crest(crest_width_feet)
    return PowerCurve(
        coefficient=CIPOLLETTI_COEFFICIENT * crest_width_feet,
        exponent=WEIR_EXPONENT,
        low_head_feet=MINIMUM_HEAD_FEET,
        high_head_feet=_crest_limit(crest_width_feet),
        label=f"{crest_width_feet} ft Cipolletti weir",
        head_offset_feet=head_offset_feet,
    )


def rectangular_suppressed(
    crest_width_feet: Decimal, head_offset_feet: Decimal = Decimal("0")
) -> PowerCurve:
    """A rectangular weir running the full width of the approach box."""

    _check_crest(crest_width_feet)
    return PowerCurve(
        coefficient=FRANCIS_COEFFICIENT * crest_width_feet,
        exponent=WEIR_EXPONENT,
        low_head_feet=MINIMUM_HEAD_FEET,
        high_head_feet=_crest_limit(crest_width_feet),
        label=f"{crest_width_feet} ft suppressed rectangular weir",
        head_offset_feet=head_offset_feet,
    )


def v_notch_ninety(head_offset_feet: Decimal = Decimal("0")) -> PowerCurve:
    """A ninety degree V notch, for the small flows."""

    return PowerCurve(
        coefficient=V_NOTCH_90_COEFFICIENT,
        exponent=V_NOTCH_90_EXPONENT,
        low_head_feet=Decimal("0.1"),
        high_head_feet=Decimal("1.25"),
        label="90 degree V notch weir",
        head_offset_feet=head_offset_feet,
    )


@dataclass(frozen=True, slots=True)
class ContractedRectangularWeir:
    """A rectangular weir with end contractions, where the crest shortens.

    Francis takes a tenth of the head off each end, so the effective crest
    depends on the head and the rating is not a power curve. It is still a
    rating curve and every caller treats it as one.
    """

    crest_width_feet: Decimal
    head_offset_feet: Decimal = Decimal("0")
    contractions: int = 2

    def __post_init__(self) -> None:
        _check_crest(self.crest_width_feet)
        if self.contractions not in (1, 2):
            raise ValidationError(
                f"a rectangular weir has one or two end contractions, not {self.contractions}"
            )

    @property
    def min_head_feet(self) -> Decimal:
        return MINIMUM_HEAD_FEET

    @property
    def max_head_feet(self) -> Decimal:
        return _crest_limit(self.crest_width_feet)

    def effective_crest_feet(self, head_feet: Decimal) -> Decimal:
        shortened = self.crest_width_feet - (
            CONTRACTION_PER_HEAD
            * Decimal(self.contractions)
            / 2
            * (head_feet + self.head_offset_feet)
        )
        if shortened <= 0:
            raise HeadOutOfRangeError(head_feet, self.min_head_feet, self.max_head_feet)
        return shortened

    def discharge_cfs(self, head_feet: Decimal) -> Decimal:
        if head_feet < self.min_head_feet or head_feet > self.max_head_feet:
            raise HeadOutOfRangeError(head_feet, self.min_head_feet, self.max_head_feet)
        head = head_feet + self.head_offset_feet
        crest = self.effective_crest_feet(head_feet)
        return round_rate(FRANCIS_COEFFICIENT * crest * head**WEIR_EXPONENT)

    def describe(self) -> str:
        return (
            f"{self.crest_width_feet} ft contracted rectangular weir with "
            f"{self.contractions} end contractions, good from {self.min_head_feet} "
            f"to {self.max_head_feet} ft"
        )
