"""The calendar the district keeps its books on.

A water year runs from the first of October through the end of the following
September, which is the federal gauging convention and the one every decree in
the basin is written against. The irrigation season is a shorter window inside
it that the board declares each spring, and it may not run past the end of the
water year it belongs to. Deliveries outside the declared season are a separate
kind of record.

Every span in this module is half open. A run window that closes at 06:00 and
one that opens at 06:00 do not overlap, and a day boundary belongs to the day
that starts there.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal

from .errors import ValidationError

WATER_YEAR_START_MONTH = 10
WATER_YEAR_START_DAY = 1

DEFAULT_SEASON_OPEN = (4, 15)
DEFAULT_SEASON_CLOSE = (10, 1)


def water_year_of(day: date) -> int:
    """The water year a calendar day falls in."""

    if day.month >= WATER_YEAR_START_MONTH:
        return day.year + 1
    return day.year


def water_year_bounds(water_year: int) -> tuple[date, date]:
    """First day of a water year and the first day after it."""

    if water_year < 1850 or water_year > 2200:
        raise ValidationError(f"water year {water_year} is outside anything this district has")
    start = date(water_year - 1, WATER_YEAR_START_MONTH, WATER_YEAR_START_DAY)
    end = date(water_year, WATER_YEAR_START_MONTH, WATER_YEAR_START_DAY)
    return start, end


def parse_day(text: str) -> date:
    """Parse a day written the way the office writes it."""

    try:
        return date.fromisoformat(text)
    except ValueError as exc:
        raise ValidationError(f"{text!r} is not a date in year-month-day form") from exc


def parse_instant(text: str) -> datetime:
    """Parse a timestamp, allowing a bare day to mean midnight that morning."""

    try:
        return datetime.fromisoformat(text)
    except ValueError as exc:
        raise ValidationError(f"{text!r} is not a timestamp this office writes") from exc


@dataclass(frozen=True, slots=True)
class Span:
    """A half open span of time, used for every run window in the system."""

    start: datetime
    end: datetime

    def __post_init__(self) -> None:
        if self.end <= self.start:
            raise ValidationError(
                f"a span must end after it starts, got {self.start} to {self.end}"
            )

    @property
    def seconds(self) -> Decimal:
        return Decimal(str((self.end - self.start).total_seconds()))

    @property
    def days(self) -> Decimal:
        return self.seconds / Decimal("86400")

    def overlaps(self, other: Span) -> bool:
        return self.start < other.end and other.start < self.end

    def intersect(self, other: Span) -> Span | None:
        start = max(self.start, other.start)
        end = min(self.end, other.end)
        if end <= start:
            return None
        return Span(start, end)

    def contains(self, moment: datetime) -> bool:
        return self.start <= moment < self.end

    def split_on_days(self) -> list[Span]:
        """Cut the span at midnight, so a volume can be posted by day."""

        pieces: list[Span] = []
        cursor = self.start
        while cursor < self.end:
            midnight = datetime.combine(cursor.date() + timedelta(days=1), cursor.min.time())
            stop = min(midnight, self.end)
            pieces.append(Span(cursor, stop))
            cursor = stop
        return pieces


@dataclass(frozen=True, slots=True)
class IrrigationSeason:
    """The declared season for one water year on one ditch."""

    water_year: int
    opened: date
    closed: date

    def __post_init__(self) -> None:
        if self.closed <= self.opened:
            raise ValidationError(
                f"season {self.water_year} closes {self.closed} which is not after {self.opened}"
            )
        first, after = water_year_bounds(self.water_year)
        if self.opened < first or self.closed > after:
            raise ValidationError(
                f"season {self.water_year} runs {self.opened} to {self.closed}, "
                f"which leaves water year {self.water_year}"
            )

    @classmethod
    def default_for(cls, water_year: int) -> IrrigationSeason:
        return cls(
            water_year=water_year,
            opened=date(water_year, *DEFAULT_SEASON_OPEN),
            closed=date(water_year, *DEFAULT_SEASON_CLOSE),
        )

    @property
    def length_days(self) -> int:
        return (self.closed - self.opened).days

    def covers(self, day: date) -> bool:
        return self.opened <= day < self.closed

    def as_span(self) -> Span:
        return Span(
            datetime.combine(self.opened, datetime.min.time()),
            datetime.combine(self.closed, datetime.min.time()),
        )
