from datetime import date, datetime
from decimal import Decimal

import pytest

from headgate.errors import ValidationError
from headgate.wateryear import (
    IrrigationSeason,
    Span,
    parse_day,
    parse_instant,
    water_year_bounds,
    water_year_of,
)


@pytest.mark.parametrize(
    ("day", "expected"),
    [
        (date(2024, 9, 30), 2024),
        (date(2024, 10, 1), 2025),
        (date(2025, 1, 4), 2025),
        (date(2025, 9, 30), 2025),
    ],
)
def test_the_water_year_turns_over_on_the_first_of_october(day: date, expected: int) -> None:
    assert water_year_of(day) == expected


def test_water_year_bounds_are_half_open() -> None:
    first, after = water_year_bounds(2025)
    assert first == date(2024, 10, 1)
    assert after == date(2025, 10, 1)
    assert water_year_of(first) == 2025


def test_an_impossible_water_year_is_refused() -> None:
    with pytest.raises(ValidationError, match="outside anything"):
        water_year_bounds(1700)


def test_days_and_instants_parse_or_say_why_not() -> None:
    assert parse_day("2025-04-15") == date(2025, 4, 15)
    assert parse_instant("2025-04-15T06:30") == datetime(2025, 4, 15, 6, 30)
    with pytest.raises(ValidationError, match="year-month-day"):
        parse_day("15/04/2025")
    with pytest.raises(ValidationError, match="timestamp"):
        parse_instant("half past six")


def test_a_span_must_end_after_it_starts() -> None:
    with pytest.raises(ValidationError, match="must end after"):
        Span(datetime(2025, 5, 1, 6), datetime(2025, 5, 1, 6))


def test_span_length_is_reported_in_seconds_and_days() -> None:
    span = Span(datetime(2025, 5, 1, 6), datetime(2025, 5, 2, 6))
    assert span.seconds == Decimal("86400.0")
    assert span.days == Decimal("1")


def test_touching_spans_do_not_overlap() -> None:
    first = Span(datetime(2025, 5, 1, 0), datetime(2025, 5, 1, 6))
    second = Span(datetime(2025, 5, 1, 6), datetime(2025, 5, 1, 12))
    assert not first.overlaps(second)
    assert first.intersect(second) is None


def test_overlapping_spans_intersect_to_the_shared_piece() -> None:
    first = Span(datetime(2025, 5, 1, 0), datetime(2025, 5, 1, 8))
    second = Span(datetime(2025, 5, 1, 6), datetime(2025, 5, 1, 12))
    shared = first.intersect(second)
    assert shared == Span(datetime(2025, 5, 1, 6), datetime(2025, 5, 1, 8))


def test_a_span_contains_its_start_and_not_its_end() -> None:
    span = Span(datetime(2025, 5, 1, 0), datetime(2025, 5, 1, 6))
    assert span.contains(datetime(2025, 5, 1, 0))
    assert not span.contains(datetime(2025, 5, 1, 6))


def test_splitting_on_days_cuts_at_midnight() -> None:
    span = Span(datetime(2025, 5, 1, 18), datetime(2025, 5, 3, 6))
    pieces = span.split_on_days()
    assert [(p.start.day, p.end.day) for p in pieces] == [(1, 2), (2, 3), (3, 3)]
    assert sum((p.seconds for p in pieces), Decimal("0")) == span.seconds


def test_the_default_season_sits_inside_its_water_year() -> None:
    season = IrrigationSeason.default_for(2025)
    assert season.opened == date(2025, 4, 15)
    assert season.closed == date(2025, 10, 1)
    assert season.length_days == 169
    assert season.covers(date(2025, 7, 4))
    assert not season.covers(date(2025, 10, 1))


def test_a_season_that_closes_before_it_opens_is_refused() -> None:
    with pytest.raises(ValidationError, match="not after"):
        IrrigationSeason(2025, date(2025, 6, 1), date(2025, 5, 1))


def test_a_season_may_not_leave_its_water_year() -> None:
    with pytest.raises(ValidationError, match="leaves water year"):
        IrrigationSeason(2025, date(2025, 4, 15), date(2025, 11, 1))


def test_a_season_as_a_span_covers_whole_days() -> None:
    span = IrrigationSeason.default_for(2025).as_span()
    assert span.start == datetime(2025, 4, 15)
    assert span.days == Decimal("169")
