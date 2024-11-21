"""Units of water, and the conversions between them.

Rates are cubic feet per second and volumes are acre feet. Both are carried as
Decimal because this is an accounting system: a season total is compared
against a decreed cap and a rounding drift of a few hundredths of an acre foot
is a real difference of opinion with a water commissioner.

A miner's inch is not one thing. It is a statutory fraction of a cubic foot per
second and the fraction differs by state, so the conversion needs to know which
statute the ditch sits under.
"""

from __future__ import annotations

from collections.abc import Iterable
from decimal import ROUND_HALF_UP, Decimal
from enum import Enum

from .errors import ValidationError

CUBIC_FEET_PER_ACRE_FOOT = Decimal("43560")
SECONDS_PER_DAY = Decimal("86400")
GALLONS_PER_CUBIC_FOOT = Decimal("7.48051948")

#: One cubic foot per second running for a full day.
ACRE_FEET_PER_CFS_DAY = SECONDS_PER_DAY / CUBIC_FEET_PER_ACRE_FOOT

VOLUME_PLACES = Decimal("0.0001")
RATE_PLACES = Decimal("0.001")


class MinersInchStandard(Enum):
    """Statutory miner's inches to the cubic foot per second."""

    COLORADO = Decimal("38.4")
    ARIZONA = Decimal("40")
    MONTANA = Decimal("40")
    OREGON = Decimal("40")
    IDAHO = Decimal("50")
    KANSAS = Decimal("50")
    NEBRASKA = Decimal("50")
    NEW_MEXICO = Decimal("50")
    UTAH = Decimal("50")

    @property
    def inches_per_cfs(self) -> Decimal:
        return Decimal(self.value)


def round_volume(acre_feet: Decimal) -> Decimal:
    """Round a volume to the four places the delivery record carries."""

    return acre_feet.quantize(VOLUME_PLACES, rounding=ROUND_HALF_UP)


def round_rate(cfs: Decimal) -> Decimal:
    """Round a rate to the three places a staff gauge can justify."""

    return cfs.quantize(RATE_PLACES, rounding=ROUND_HALF_UP)


def total_volume(values: Iterable[Decimal]) -> Decimal:
    """Add volumes up and round the answer once, at the end."""

    return round_volume(sum(values, Decimal("0")))


def total_rate(values: Iterable[Decimal]) -> Decimal:
    """Add rates up and round the answer once, at the end."""

    return round_rate(sum(values, Decimal("0")))


def check_rate(cfs: Decimal) -> Decimal:
    """Reject a rate that is negative or absurd, and round what is left."""

    if cfs < 0:
        raise ValidationError(f"rate may not be negative, got {cfs}")
    if cfs > Decimal("10000"):
        raise ValidationError(f"rate {cfs} cfs is larger than any ditch on the system")
    return round_rate(cfs)


def check_volume(acre_feet: Decimal) -> Decimal:
    """Reject a negative volume, and round what is left."""

    if acre_feet < 0:
        raise ValidationError(f"volume may not be negative, got {acre_feet}")
    return round_volume(acre_feet)


def cfs_for_seconds(cfs: Decimal, seconds: Decimal) -> Decimal:
    """Volume in acre feet from a steady rate held for a number of seconds."""

    if seconds < 0:
        raise ValidationError(f"duration may not be negative, got {seconds} seconds")
    return round_volume(check_rate(cfs) * seconds / CUBIC_FEET_PER_ACRE_FOOT)


def cfs_days(cfs: Decimal, days: Decimal) -> Decimal:
    """Volume in acre feet from a steady rate held for a number of days."""

    return cfs_for_seconds(cfs, days * SECONDS_PER_DAY)


def acre_feet_to_cfs(acre_feet: Decimal, seconds: Decimal) -> Decimal:
    """The steady rate that would deliver a volume over a span of seconds."""

    if seconds <= 0:
        raise ValidationError("cannot spread a volume over a span of no time")
    return round_rate(check_volume(acre_feet) * CUBIC_FEET_PER_ACRE_FOOT / seconds)


def miners_inches_to_cfs(inches: Decimal, standard: MinersInchStandard) -> Decimal:
    """Convert miner's inches to cubic feet per second under a state standard."""

    if inches < 0:
        raise ValidationError(f"miner's inches may not be negative, got {inches}")
    return round_rate(inches / standard.inches_per_cfs)


def cfs_to_miners_inches(cfs: Decimal, standard: MinersInchStandard) -> Decimal:
    """Convert cubic feet per second to miner's inches under a state standard."""

    return (check_rate(cfs) * standard.inches_per_cfs).quantize(
        Decimal("0.01"), rounding=ROUND_HALF_UP
    )


def gpm_to_cfs(gallons_per_minute: Decimal) -> Decimal:
    """Convert gallons per minute, which is how a pump is rated, to cfs."""

    if gallons_per_minute < 0:
        raise ValidationError("a pump rate may not be negative")
    return round_rate(gallons_per_minute / (GALLONS_PER_CUBIC_FOOT * 60))


def depth_over_acres(acre_feet: Decimal, acres: Decimal) -> Decimal:
    """Applied depth in inches, which is how an irrigator thinks about it."""

    if acres <= 0:
        raise ValidationError("a place of use with no acres has no applied depth")
    return (check_volume(acre_feet) / acres * 12).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
