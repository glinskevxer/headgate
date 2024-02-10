"""Ground the water is decreed to, and what is growing on it.

A place of use is the acreage a right may be applied to, parcel by parcel. It
matters twice over. The season's demand is built off the crop on each parcel,
and a transfer of a right has to dry up the acreage it came from, so the
register has to be able to say which parcels went dry and when.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, replace
from datetime import date
from decimal import Decimal
from enum import Enum

from ..errors import NotFoundError, PolicyError, ValidationError
from ..ids import AccountNumber, TurnoutCode

PARCEL_PATTERN = re.compile(r"^[0-9]{2}-[0-9]{3}-[0-9]{3}$")


class CropCode(Enum):
    """The crops this district writes on an assessment roll."""

    ALFALFA = "alfalfa"
    PASTURE = "pasture"
    SMALL_GRAIN = "small_grain"
    CORN = "corn"
    ORCHARD = "orchard"
    FALLOW = "fallow"

    @property
    def is_irrigated(self) -> bool:
        return self is not CropCode.FALLOW


@dataclass(frozen=True, slots=True)
class Parcel:
    """One assessor's parcel under one turnout."""

    parcel_id: str
    account: AccountNumber
    turnout: TurnoutCode
    irrigated_acres: Decimal
    crop: CropCode
    dried_up_on: date | None = None

    def __post_init__(self) -> None:
        if not PARCEL_PATTERN.match(self.parcel_id):
            raise ValidationError(f"{self.parcel_id!r} is not a parcel number")
        if self.irrigated_acres <= 0:
            raise ValidationError(f"parcel {self.parcel_id} has no irrigated acres")
        if self.crop is CropCode.FALLOW and self.dried_up_on is None:
            raise ValidationError(
                f"parcel {self.parcel_id} is fallow with no date it went out of production"
            )

    def in_production_on(self, day: date) -> bool:
        return self.dried_up_on is None or day < self.dried_up_on

    def acres_on(self, day: date) -> Decimal:
        return self.irrigated_acres if self.in_production_on(day) else Decimal("0")


@dataclass(frozen=True, slots=True)
class PlaceOfUse:
    """Every parcel the ditch serves, with the acreage cap it is held to."""

    parcels: tuple[Parcel, ...]
    decreed_acres: Decimal | None = None

    def __post_init__(self) -> None:
        seen: set[str] = set()
        for parcel in self.parcels:
            if parcel.parcel_id in seen:
                raise ValidationError(f"parcel {parcel.parcel_id} is listed twice")
            seen.add(parcel.parcel_id)
        if self.decreed_acres is not None and self.decreed_acres <= 0:
            raise ValidationError("a decreed acreage of zero is not a place of use")

    def parcel(self, parcel_id: str) -> Parcel:
        for parcel in self.parcels:
            if parcel.parcel_id == parcel_id:
                return parcel
        raise NotFoundError("parcel", parcel_id)

    def acres_on(self, day: date) -> Decimal:
        return sum((parcel.acres_on(day) for parcel in self.parcels), Decimal("0"))

    def acres_under(self, turnout: TurnoutCode, day: date) -> Decimal:
        return sum(
            (parcel.acres_on(day) for parcel in self.parcels if parcel.turnout == turnout),
            Decimal("0"),
        )

    def acres_of(self, account: AccountNumber, day: date) -> Decimal:
        return sum(
            (parcel.acres_on(day) for parcel in self.parcels if parcel.account == account),
            Decimal("0"),
        )

    def turnouts(self, day: date) -> tuple[TurnoutCode, ...]:
        served = {parcel.turnout for parcel in self.parcels if parcel.in_production_on(day)}
        return tuple(sorted(served))

    def over_decree_on(self, day: date) -> Decimal:
        """Acres irrigated beyond what the decree allows, zero if within it."""

        if self.decreed_acres is None:
            return Decimal("0")
        excess = self.acres_on(day) - self.decreed_acres
        return excess if excess > 0 else Decimal("0")

    def dry_up(self, parcel_id: str, on: date) -> PlaceOfUse:
        """Take a parcel out of production, which a transfer has to do."""

        parcel = self.parcel(parcel_id)
        if not parcel.in_production_on(on):
            raise PolicyError(f"parcel {parcel_id} was already dry on {on}")
        dried = replace(parcel, dried_up_on=on, crop=CropCode.FALLOW)
        others = tuple(item for item in self.parcels if item.parcel_id != parcel_id)
        return replace(self, parcels=(*others, dried))
