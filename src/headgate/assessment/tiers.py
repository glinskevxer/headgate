"""The rate schedule the board sets each spring.

Two pieces make up a bill. Every share pays the same flat charge whether it
irrigated or not, because the ditch has to be cleaned either way. On top of
that, water delivered is charged through bands that get dearer as they go, so
the man who runs all August pays for the trouble he causes.

The bands are progressive, not a lookup. Two hundred acre feet is not charged
at the two hundred acre foot rate; the first band is charged at the first rate,
the next at the next, and so on, which is the same way an income tax works and
the same way this district has billed since the sixties.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from ..errors import PolicyError, ValidationError
from ..money import Money


@dataclass(frozen=True, slots=True)
class Band:
    """One step of the schedule, up to a ceiling."""

    upper_af: Decimal | None
    rate_per_af: Money

    def __post_init__(self) -> None:
        if self.upper_af is not None and self.upper_af <= 0:
            raise ValidationError("a band that ends at or below nothing is not a band")
        if self.rate_per_af.cents < 0:
            raise ValidationError("a band that pays the shareholder is not a rate")

    @property
    def is_open_ended(self) -> bool:
        return self.upper_af is None


@dataclass(frozen=True, slots=True)
class RateSchedule:
    """What the board adopted for one water year."""

    water_year: int
    per_share: Money
    bands: tuple[Band, ...]
    minimum_bill: Money = Money(0)

    def __post_init__(self) -> None:
        if not self.bands:
            raise ValidationError(f"the {self.water_year} schedule has no bands")
        if not self.bands[-1].is_open_ended:
            raise ValidationError(
                f"the {self.water_year} schedule stops at {self.bands[-1].upper_af} acre feet "
                "with nothing above it"
            )
        ceiling = Decimal("0")
        for band in self.bands[:-1]:
            if band.upper_af is None:
                raise ValidationError(
                    f"the {self.water_year} schedule has an open band before the top of it"
                )
            if band.upper_af <= ceiling:
                raise ValidationError(
                    f"the {self.water_year} schedule has a band ending at {band.upper_af}, "
                    f"which is not above {ceiling}"
                )
            ceiling = band.upper_af
        if self.per_share.cents < 0:
            raise ValidationError("a share charge that pays the shareholder is not a charge")

    def band_for(self, acre_feet: Decimal) -> Band:
        """The band the last acre foot of a delivery falls in."""

        if acre_feet < 0:
            raise ValidationError("a negative delivery has no band")
        ceiling = Decimal("0")
        for band in self.bands:
            if band.upper_af is None or acre_feet <= band.upper_af:
                return band
            ceiling = band.upper_af
        raise PolicyError(f"{acre_feet} acre feet is above the top band at {ceiling}")

    def water_charge(self, acre_feet: Decimal) -> Money:
        """Charge a delivery through the bands, a step at a time."""

        if acre_feet < 0:
            raise ValidationError("a negative delivery cannot be charged")
        charged = Money.zero()
        floor = Decimal("0")
        for band in self.bands:
            ceiling = band.upper_af if band.upper_af is not None else acre_feet
            if acre_feet <= floor:
                break
            inside = min(acre_feet, ceiling) - floor
            if inside > 0:
                charged = charged + band.rate_per_af.times(inside)
            floor = ceiling
        return charged

    def share_charge(self, shares: Decimal) -> Money:
        if shares < 0:
            raise ValidationError("a negative shareholding is not a shareholding")
        return self.per_share.times(shares)

    def bill_for(self, shares: Decimal, acre_feet: Decimal) -> Money:
        """The whole charge, before any credit and after the minimum."""

        total = self.share_charge(shares) + self.water_charge(acre_feet)
        if total < self.minimum_bill:
            return self.minimum_bill
        return total

    @property
    def top_of_the_schedule(self) -> Decimal | None:
        return self.bands[-2].upper_af if len(self.bands) > 1 else None


def flat_schedule(water_year: int, per_share: Money, per_acre_foot: Money) -> RateSchedule:
    """A schedule with one rate for every acre foot, which small districts use."""

    return RateSchedule(
        water_year=water_year,
        per_share=per_share,
        bands=(Band(None, per_acre_foot),),
    )
