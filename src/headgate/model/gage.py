"""The gaging record: what the creek was doing, day by day.

A gage produces one number a day and the number has a grade on it. Winter
records are ice affected and the published number is somebody's judgement of
what the creek would have been doing without the ice. A record with a broken
float is worse than that: there is no number at all, and the day is missing.

A missing day is not a zero. Every total in here refuses to pretend otherwise:
a volume over a span with holes in it is reported with the holes named, and a
span with too many holes will not give a volume at all, because a season total
that quietly skipped eleven days in July is the sort of number that ends up in
a court filing.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import date, timedelta
from decimal import Decimal
from enum import Enum

from ..errors import NotFoundError, PolicyError, ValidationError
from ..units import ACRE_FEET_PER_CFS_DAY, round_rate, round_volume

DEFAULT_COVERAGE_FLOOR = Decimal("0.9")


class RecordGrade(Enum):
    """What the gage record is worth."""

    MEASURED = "measured"
    ESTIMATED = "estimated"
    ICE_AFFECTED = "ice_affected"

    @property
    def is_evidence(self) -> bool:
        return self is RecordGrade.MEASURED


@dataclass(frozen=True, slots=True)
class DailyMean:
    """One day at one gage."""

    day: date
    mean_cfs: Decimal
    grade: RecordGrade = RecordGrade.MEASURED

    def __post_init__(self) -> None:
        if self.mean_cfs < 0:
            raise ValidationError(f"the gage read {self.mean_cfs} cfs on {self.day}")

    @property
    def volume_af(self) -> Decimal:
        return round_volume(self.mean_cfs * ACRE_FEET_PER_CFS_DAY)


@dataclass(frozen=True, slots=True)
class Hydrograph:
    """A gage's record, oldest day first."""

    gage: str
    days: tuple[DailyMean, ...] = ()

    def __post_init__(self) -> None:
        seen: set[date] = set()
        for item in self.days:
            if item.day in seen:
                raise ValidationError(f"gage {self.gage} has two records for {item.day}")
            seen.add(item.day)
        order = [item.day for item in self.days]
        if order != sorted(order):
            raise ValidationError(f"the record for gage {self.gage} is out of order")

    def add(self, reading: DailyMean) -> Hydrograph:
        if any(item.day == reading.day for item in self.days):
            raise PolicyError(f"gage {self.gage} already has a record for {reading.day}")
        return replace(self, days=tuple(sorted((*self.days, reading), key=lambda item: item.day)))

    def on(self, day: date) -> DailyMean:
        for item in self.days:
            if item.day == day:
                return item
        raise NotFoundError("gage record", f"{self.gage} on {day}")

    def between(self, first: date, last: date) -> tuple[DailyMean, ...]:
        return tuple(item for item in self.days if first <= item.day < last)

    def missing_days(self, first: date, last: date) -> tuple[date, ...]:
        if last <= first:
            raise ValidationError("a span of gage record has to end after it starts")
        have = {item.day for item in self.between(first, last)}
        wanted = (first + timedelta(days=offset) for offset in range((last - first).days))
        return tuple(day for day in wanted if day not in have)

    def coverage(self, first: date, last: date) -> Decimal:
        total = (last - first).days
        if total <= 0:
            raise ValidationError("a span of gage record has to end after it starts")
        missing = len(self.missing_days(first, last))
        return (Decimal(total - missing) / Decimal(total)).quantize(Decimal("0.001"))

    def volume_af(
        self, first: date, last: date, coverage_floor: Decimal = DEFAULT_COVERAGE_FLOOR
    ) -> Decimal:
        """The volume over a span, refusing a span with too many holes in it."""

        covered = self.coverage(first, last)
        if covered < coverage_floor:
            raise PolicyError(
                f"gage {self.gage} covers {covered} of {first} to {last}, which is under the "
                f"{coverage_floor} the district will total"
            )
        return round_volume(
            sum((item.volume_af for item in self.between(first, last)), Decimal("0"))
        )

    def mean_cfs(self, first: date, last: date) -> Decimal:
        found = self.between(first, last)
        if not found:
            raise PolicyError(f"gage {self.gage} has no record between {first} and {last}")
        return round_rate(
            sum((item.mean_cfs for item in found), Decimal("0")) / Decimal(len(found))
        )

    def peak(self, first: date, last: date) -> DailyMean:
        found = self.between(first, last)
        if not found:
            raise PolicyError(f"gage {self.gage} has no record between {first} and {last}")
        return max(found, key=lambda item: (item.mean_cfs, item.day))

    def graded(self, grade: RecordGrade) -> tuple[DailyMean, ...]:
        return tuple(item for item in self.days if item.grade is grade)

    def is_proved(self, first: date, last: date) -> bool:
        """Whether every day in a span was measured rather than judged."""

        found = self.between(first, last)
        if not found:
            return False
        return all(item.grade.is_evidence for item in found)

    def monthly_volumes(self, water_year: int) -> dict[int, Decimal]:
        """The volume by calendar month, for the months that have any record."""

        found: dict[int, Decimal] = {}
        for item in self.days:
            year = item.day.year + 1 if item.day.month >= 10 else item.day.year
            if year != water_year:
                continue
            found[item.day.month] = found.get(item.day.month, Decimal("0")) + item.volume_af
        return {month: round_volume(value) for month, value in sorted(found.items())}
