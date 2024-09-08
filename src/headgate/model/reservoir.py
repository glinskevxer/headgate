"""The reservoir at the head of the system.

Storage is a different animal from direct flow and the differences all bite.

A storage right fills once a year. Water let out in June and caught again in
July is a second fill of the same right, and unless the decree says otherwise
that is not allowed, however much water is running past.

The pool has a bottom nobody can use. Below the outlet there are several
hundred acre feet that are in the reservoir and are not in anybody's account,
and a report that counts them as water is a report that promises deliveries the
district cannot make.

And it can spill. When the pool is full and the creek keeps coming, the water
that goes over the top is gone, and whose account it came out of is a decision
the district has to have made in advance rather than in August.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import date
from decimal import Decimal

from ..errors import PolicyError, ValidationError
from ..ids import DecreeNumber
from ..units import round_volume
from ..wateryear import water_year_of


@dataclass(frozen=True, slots=True)
class Reservoir:
    """The pool, its bottom, and the right that fills it."""

    name: str
    decree: DecreeNumber
    capacity_af: Decimal
    dead_pool_af: Decimal
    fill_opens: tuple[int, int] = (11, 1)
    fill_closes: tuple[int, int] = (7, 1)

    def __post_init__(self) -> None:
        if self.capacity_af <= 0:
            raise ValidationError(f"reservoir {self.name} holds nothing")
        if self.dead_pool_af < 0:
            raise ValidationError(f"reservoir {self.name} has a negative dead pool")
        if self.dead_pool_af >= self.capacity_af:
            raise ValidationError(
                f"reservoir {self.name} has a dead pool of {self.dead_pool_af} in a "
                f"{self.capacity_af} acre foot pool"
            )

    @property
    def usable_af(self) -> Decimal:
        return round_volume(self.capacity_af - self.dead_pool_af)

    def fill_window(self, water_year: int) -> tuple[date, date]:
        """The days the decree lets this reservoir store water in."""

        opens = date(water_year - 1, *self.fill_opens)
        closes = date(water_year, *self.fill_closes)
        return opens, closes

    def may_fill_on(self, day: date) -> bool:
        opens, closes = self.fill_window(water_year_of(day))
        return opens <= day < closes


@dataclass(frozen=True, slots=True)
class PoolState:
    """What is in the reservoir, and what it is allowed to do next."""

    reservoir: Reservoir
    water_year: int
    contents_af: Decimal
    filled_af: Decimal = Decimal("0")
    spilled_af: Decimal = Decimal("0")
    released_af: Decimal = Decimal("0")
    fill_finished: bool = False

    def __post_init__(self) -> None:
        if self.contents_af < 0:
            raise ValidationError(f"{self.reservoir.name} cannot hold a negative volume")
        if self.contents_af > self.reservoir.capacity_af:
            raise ValidationError(
                f"{self.reservoir.name} holds {self.contents_af} in a "
                f"{self.reservoir.capacity_af} acre foot pool"
            )

    @property
    def usable_af(self) -> Decimal:
        usable = self.contents_af - self.reservoir.dead_pool_af
        return round_volume(usable) if usable > 0 else Decimal("0")

    @property
    def space_af(self) -> Decimal:
        return round_volume(self.reservoir.capacity_af - self.contents_af)

    @property
    def is_full(self) -> bool:
        return self.contents_af >= self.reservoir.capacity_af

    @property
    def percent_full(self) -> Decimal:
        return (self.contents_af / self.reservoir.capacity_af * 100).quantize(Decimal("0.1"))

    def fill(self, inflow_af: Decimal, on: date) -> PoolState:
        """Store what will fit, spill the rest, and note if the fill is done."""

        if inflow_af < 0:
            raise ValidationError("a reservoir cannot fill on a negative inflow")
        if water_year_of(on) != self.water_year:
            raise PolicyError(
                f"{on} is not in water year {self.water_year}, which this pool is keeping"
            )
        if not self.reservoir.may_fill_on(on):
            raise PolicyError(
                f"{self.reservoir.name} may not store water on {on}, outside its fill season"
            )
        if self.fill_finished:
            raise PolicyError(
                f"{self.reservoir.name} has already had its one fill for {self.water_year}"
            )
        stored = min(inflow_af, self.space_af)
        spilled = round_volume(inflow_af - stored)
        return replace(
            self,
            contents_af=round_volume(self.contents_af + stored),
            filled_af=round_volume(self.filled_af + stored),
            spilled_af=round_volume(self.spilled_af + spilled),
        )

    def release(self, volume_af: Decimal) -> PoolState:
        """Let water out, which ends the fill for the year."""

        if volume_af < 0:
            raise ValidationError("a reservoir cannot release a negative volume")
        if volume_af > self.usable_af:
            raise PolicyError(
                f"{self.reservoir.name} has {self.usable_af} acre feet above the outlet and "
                f"was asked for {volume_af}"
            )
        return replace(
            self,
            contents_af=round_volume(self.contents_af - volume_af),
            released_af=round_volume(self.released_af + volume_af),
            fill_finished=True,
        )

    def carry_over(self, next_water_year: int, limit_af: Decimal | None = None) -> PoolState:
        """Roll what is left into the next year, spilling anything over the cap."""

        if next_water_year <= self.water_year:
            raise PolicyError(f"{next_water_year} does not come after {self.water_year}")
        kept = self.usable_af if limit_af is None else min(self.usable_af, limit_af)
        lost = round_volume(self.usable_af - kept)
        return PoolState(
            reservoir=self.reservoir,
            water_year=next_water_year,
            contents_af=round_volume(kept + self.reservoir.dead_pool_af),
            spilled_af=lost,
        )
