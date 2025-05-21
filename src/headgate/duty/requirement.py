"""What the crop needs, month by month, before anybody loses any of it.

The net requirement is what the plant uses less what the rain gives it. It is
published by the state for each crop and each part of the valley, and this
district uses the table for the middle bench, which is what the numbers below
are. Nothing here is measured on this ditch; it is the reference the season is
compared against.

The gross requirement is the net divided by the efficiency of the way the water
is put on. Flood irrigation on gravel throws most of it away, a wheel line does
better, and a pivot better still. That division is the whole reason a decree of
four acre feet to the acre is not extravagant.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal

from ..errors import PolicyError, ValidationError
from ..model.parcel import Application, CropCode

SEASON_MONTHS = (4, 5, 6, 7, 8, 9)
INCHES_PER_FOOT = Decimal("12")


@dataclass(frozen=True, slots=True)
class MonthlyRequirement:
    """The net requirement for one crop, in inches, month by month."""

    crop: CropCode
    inches: tuple[Decimal, ...]

    def __post_init__(self) -> None:
        if len(self.inches) != len(SEASON_MONTHS):
            raise ValidationError(
                f"the table for {self.crop.value} covers {len(self.inches)} months and the "
                f"season is {len(SEASON_MONTHS)}"
            )
        if any(value < 0 for value in self.inches):
            raise ValidationError(f"the table for {self.crop.value} has a negative month in it")

    def for_month(self, month: int) -> Decimal:
        if month not in SEASON_MONTHS:
            return Decimal("0")
        return self.inches[SEASON_MONTHS.index(month)]

    @property
    def season_inches(self) -> Decimal:
        return sum(self.inches, Decimal("0"))

    @property
    def peak_month(self) -> int:
        highest = max(self.inches)
        return SEASON_MONTHS[self.inches.index(highest)]


def _table(crop: CropCode, *inches: str) -> MonthlyRequirement:
    return MonthlyRequirement(crop=crop, inches=tuple(Decimal(value) for value in inches))


REQUIREMENTS: dict[CropCode, MonthlyRequirement] = {
    CropCode.ALFALFA: _table(CropCode.ALFALFA, "1.9", "4.6", "7.1", "8.2", "6.4", "3.1"),
    CropCode.PASTURE: _table(CropCode.PASTURE, "1.6", "4.0", "6.2", "7.0", "5.5", "2.8"),
    CropCode.SMALL_GRAIN: _table(CropCode.SMALL_GRAIN, "1.4", "4.1", "6.8", "4.9", "0.6", "0"),
    CropCode.CORN: _table(CropCode.CORN, "0.4", "2.2", "5.9", "8.6", "6.1", "1.2"),
    CropCode.ORCHARD: _table(CropCode.ORCHARD, "2.1", "4.4", "6.6", "7.6", "6.0", "3.4"),
    CropCode.FALLOW: _table(CropCode.FALLOW, "0", "0", "0", "0", "0", "0"),
}


def requirement_for(crop: CropCode) -> MonthlyRequirement:
    table = REQUIREMENTS.get(crop)
    if table is None:
        raise PolicyError(f"this district has no requirement table for {crop.value}")
    return table


def net_inches(crop: CropCode, month: int | None = None) -> Decimal:
    """Net requirement for a month, or for the whole season."""

    table = requirement_for(crop)
    if month is None:
        return table.season_inches
    return table.for_month(month)


def net_acre_feet(crop: CropCode, acres: Decimal, month: int | None = None) -> Decimal:
    if acres < 0:
        raise ValidationError("a place of use with negative acres has no requirement")
    return (net_inches(crop, month) / INCHES_PER_FOOT * acres).quantize(
        Decimal("0.0001"), rounding=ROUND_HALF_UP
    )


def gross_acre_feet(
    crop: CropCode, acres: Decimal, application: Application, month: int | None = None
) -> Decimal:
    """What has to be delivered at the turnout to meet the net requirement."""

    net = net_acre_feet(crop, acres, month)
    return (net / application.efficiency).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)


def peak_rate_cfs(
    crop: CropCode, acres: Decimal, application: Application, month: int | None = None
) -> Decimal:
    """The steady rate that would meet the month's requirement, in cfs."""

    when = month if month is not None else requirement_for(crop).peak_month
    volume = gross_acre_feet(crop, acres, application, when)
    days = Decimal("30")
    return (volume / (days * Decimal("1.9835"))).quantize(Decimal("0.001"))


def losses_to_application(crop: CropCode, acres: Decimal, application: Application) -> Decimal:
    """What the application method throws away over a season."""

    return (gross_acre_feet(crop, acres, application) - net_acre_feet(crop, acres)).quantize(
        Decimal("0.0001")
    )
