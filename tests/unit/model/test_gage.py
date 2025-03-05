from datetime import date, timedelta
from decimal import Decimal

import pytest

from headgate.errors import NotFoundError, PolicyError, ValidationError
from headgate.model.gage import DailyMean, Hydrograph, RecordGrade

FIRST = date(2025, 6, 1)


def reading(offset: int, cfs: str, grade: RecordGrade = RecordGrade.MEASURED) -> DailyMean:
    return DailyMean(day=FIRST + timedelta(days=offset), mean_cfs=Decimal(cfs), grade=grade)


def hydrograph(days: int = 10) -> Hydrograph:
    return Hydrograph(
        gage="SANP-1",
        days=tuple(reading(offset, str(20 - offset)) for offset in range(days)),
    )


def test_a_negative_reading_is_refused() -> None:
    with pytest.raises(ValidationError, match="the gage read"):
        reading(0, "-1")


def test_a_day_at_a_rate_is_a_volume() -> None:
    assert reading(0, "1").volume_af == Decimal("1.9835")


def test_a_record_with_two_days_the_same_is_refused() -> None:
    with pytest.raises(ValidationError, match="two records"):
        Hydrograph(gage="SANP-1", days=(reading(0, "20"), reading(0, "19")))


def test_a_record_out_of_order_is_refused() -> None:
    with pytest.raises(ValidationError, match="out of order"):
        Hydrograph(gage="SANP-1", days=(reading(3, "17"), reading(0, "20")))


def test_a_day_can_be_added_and_looked_up() -> None:
    record = hydrograph(3).add(reading(5, "15"))
    assert record.on(FIRST + timedelta(days=5)).mean_cfs == Decimal("15")
    with pytest.raises(NotFoundError, match="no gage record"):
        record.on(FIRST + timedelta(days=9))


def test_the_same_day_twice_is_refused() -> None:
    with pytest.raises(PolicyError, match="already has a record"):
        hydrograph(3).add(reading(0, "20"))


def test_the_days_in_a_span_come_back() -> None:
    found = hydrograph().between(FIRST, FIRST + timedelta(days=3))
    assert len(found) == 3


def test_the_missing_days_are_named() -> None:
    record = Hydrograph(gage="SANP-1", days=(reading(0, "20"), reading(3, "17")))
    missing = record.missing_days(FIRST, FIRST + timedelta(days=4))
    assert missing == (FIRST + timedelta(days=1), FIRST + timedelta(days=2))


def test_a_full_record_covers_the_whole_span() -> None:
    assert hydrograph().coverage(FIRST, FIRST + timedelta(days=10)) == Decimal("1.000")


def test_a_span_with_holes_covers_less() -> None:
    record = Hydrograph(gage="SANP-1", days=(reading(0, "20"), reading(3, "17")))
    assert record.coverage(FIRST, FIRST + timedelta(days=4)) == Decimal("0.500")


def test_a_span_that_ends_before_it_starts_is_refused() -> None:
    with pytest.raises(ValidationError, match="end after it starts"):
        hydrograph().coverage(FIRST, FIRST)
    with pytest.raises(ValidationError, match="end after it starts"):
        hydrograph().missing_days(FIRST, FIRST)


def test_a_full_span_totals_to_a_volume() -> None:
    total = hydrograph().volume_af(FIRST, FIRST + timedelta(days=10))
    assert total > Decimal("0")


def test_a_span_with_too_many_holes_will_not_total() -> None:
    record = Hydrograph(gage="SANP-1", days=(reading(0, "20"), reading(3, "17")))
    with pytest.raises(PolicyError, match="under the"):
        record.volume_af(FIRST, FIRST + timedelta(days=4))


def test_a_district_can_lower_the_bar_it_will_total_at() -> None:
    record = Hydrograph(gage="SANP-1", days=(reading(0, "20"), reading(3, "17")))
    assert record.volume_af(
        FIRST, FIRST + timedelta(days=4), coverage_floor=Decimal("0.4")
    ) > Decimal("0")


def test_the_mean_and_the_peak_come_off_the_span() -> None:
    record = hydrograph()
    assert record.mean_cfs(FIRST, FIRST + timedelta(days=10)) == Decimal("15.500")
    assert record.peak(FIRST, FIRST + timedelta(days=10)).mean_cfs == Decimal("20")


def test_a_span_with_no_record_has_no_mean_or_peak() -> None:
    record = hydrograph()
    later = date(2026, 6, 1)
    with pytest.raises(PolicyError, match="no record between"):
        record.mean_cfs(later, later + timedelta(days=3))
    with pytest.raises(PolicyError, match="no record between"):
        record.peak(later, later + timedelta(days=3))


def test_ice_affected_days_are_not_evidence() -> None:
    record = hydrograph(3).add(reading(5, "15", RecordGrade.ICE_AFFECTED))
    assert len(record.graded(RecordGrade.ICE_AFFECTED)) == 1
    assert record.is_proved(FIRST, FIRST + timedelta(days=3))
    assert not record.is_proved(FIRST, FIRST + timedelta(days=6))


def test_a_span_with_no_record_is_not_proved() -> None:
    assert not hydrograph().is_proved(date(2026, 6, 1), date(2026, 6, 3))


def test_the_monthly_volumes_fall_in_the_right_water_year() -> None:
    record = Hydrograph(
        gage="SANP-1",
        days=(
            DailyMean(date(2024, 10, 2), Decimal("12")),
            DailyMean(date(2025, 6, 2), Decimal("20")),
            DailyMean(date(2025, 10, 2), Decimal("8")),
        ),
    )
    volumes = record.monthly_volumes(2025)
    assert set(volumes) == {10, 6}
    assert volumes[6] > volumes[10]
