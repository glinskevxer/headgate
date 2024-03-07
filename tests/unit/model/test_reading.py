from datetime import datetime
from decimal import Decimal

import pytest

from headgate.errors import ConflictError, NotFoundError, ValidationError
from headgate.ids import DeviceTag
from headgate.model.reading import ReadingMethod, ReadingSeries, StaffReading
from headgate.wateryear import Span

WEIR = DeviceTag("WEIR-L2-14")


def reading(day: int, head: str = "0.62", hour: int = 7, **overrides: object) -> StaffReading:
    fields: dict[str, object] = {
        "device": WEIR,
        "taken_at": datetime(2024, 6, day, hour),
        "observer": "D. Yardley",
        "head_feet": Decimal(head),
    }
    fields.update(overrides)
    return StaffReading(**fields)  # type: ignore[arg-type]


def series() -> ReadingSeries:
    return ReadingSeries(WEIR, (reading(1), reading(4, "0.58"), reading(9, "0.71")))


def test_a_reading_says_who_took_it() -> None:
    with pytest.raises(ValidationError, match="says who took it"):
        reading(1, observer="  ")


def test_a_staff_reading_carries_a_head() -> None:
    with pytest.raises(ValidationError, match="carries no head"):
        reading(1, head_feet=None)


def test_a_staff_reading_does_not_carry_a_meter_total() -> None:
    with pytest.raises(ValidationError, match="carries a meter total"):
        reading(1, meter_total_af=Decimal("4"))


def test_a_meter_reading_carries_a_total_and_no_head() -> None:
    meter = StaffReading(
        device=DeviceTag("METER-L2-20"),
        taken_at=datetime(2024, 6, 1, 7),
        observer="D. Yardley",
        method=ReadingMethod.METER_TOTAL,
        meter_total_af=Decimal("112.4"),
    )
    assert meter.meter_total_af == Decimal("112.4")
    with pytest.raises(ValidationError, match="carries no total"):
        StaffReading(
            device=DeviceTag("METER-L2-20"),
            taken_at=datetime(2024, 6, 1, 7),
            observer="D. Yardley",
            method=ReadingMethod.METER_TOTAL,
        )


def test_a_meter_reading_may_not_also_carry_a_head() -> None:
    with pytest.raises(ValidationError, match="also carries a head"):
        StaffReading(
            device=DeviceTag("METER-L2-20"),
            taken_at=datetime(2024, 6, 1, 7),
            observer="D. Yardley",
            method=ReadingMethod.METER_TOTAL,
            meter_total_af=Decimal("1"),
            head_feet=Decimal("0.2"),
        )


def test_negative_readings_are_refused() -> None:
    with pytest.raises(ValidationError, match="below the sill"):
        reading(1, head="-0.1")
    with pytest.raises(ValidationError, match="below the sill"):
        reading(1, tail_feet=Decimal("-0.2"))


def test_a_meter_total_runs_forward() -> None:
    with pytest.raises(ValidationError, match="runs forward"):
        StaffReading(
            device=DeviceTag("METER-L2-20"),
            taken_at=datetime(2024, 6, 1, 7),
            observer="D. Yardley",
            method=ReadingMethod.METER_TOTAL,
            meter_total_af=Decimal("-1"),
        )


def test_a_visual_reading_is_not_an_instrument() -> None:
    assert ReadingMethod.STAFF.is_instrument
    assert not ReadingMethod.VISUAL.is_instrument


def test_tailwater_is_optional_and_reported() -> None:
    assert not reading(1).has_tailwater
    assert reading(1, tail_feet=Decimal("0.3")).has_tailwater


def test_asking_a_meter_reading_for_a_head_is_refused() -> None:
    meter = StaffReading(
        device=DeviceTag("METER-L2-20"),
        taken_at=datetime(2024, 6, 1, 7),
        observer="D. Yardley",
        method=ReadingMethod.METER_TOTAL,
        meter_total_af=Decimal("1"),
    )
    with pytest.raises(ValidationError, match="no head to read"):
        _ = meter.head


def test_a_series_holds_one_device() -> None:
    with pytest.raises(ValidationError, match="does not belong in the series"):
        ReadingSeries(DeviceTag("WEIR-L2-20"), (reading(1),))


def test_a_series_refuses_two_readings_at_one_instant() -> None:
    with pytest.raises(ValidationError, match="two readings at"):
        ReadingSeries(WEIR, (reading(1), reading(1)))


def test_a_series_refuses_readings_out_of_order() -> None:
    with pytest.raises(ValidationError, match="out of time order"):
        ReadingSeries(WEIR, (reading(9), reading(1)))


def test_adding_a_reading_keeps_the_series_in_order() -> None:
    added = series().add(reading(6, "0.65"))
    assert [item.taken_at.day for item in added.readings] == [1, 4, 6, 9]


def test_adding_a_reading_for_another_device_is_refused() -> None:
    with pytest.raises(ValidationError, match="is not for"):
        series().add(reading(6, device=DeviceTag("WEIR-L2-20")))


def test_reading_the_same_instant_twice_is_a_conflict() -> None:
    with pytest.raises(ConflictError, match="already read at"):
        series().add(reading(4, "0.60"))


def test_readings_inside_a_span_come_back() -> None:
    span = Span(datetime(2024, 6, 2), datetime(2024, 6, 10))
    assert [item.taken_at.day for item in series().between(span)] == [4, 9]


def test_the_latest_reading_at_or_before_an_instant_is_found() -> None:
    found = series().latest_at_or_before(datetime(2024, 6, 5))
    assert found.taken_at.day == 4


def test_asking_before_the_first_reading_finds_nothing() -> None:
    with pytest.raises(NotFoundError, match="no reading"):
        series().latest_at_or_before(datetime(2024, 5, 1))


def test_the_first_reading_after_an_instant_is_found() -> None:
    assert series().first_after(datetime(2024, 6, 4, 8)).taken_at.day == 9
    with pytest.raises(NotFoundError, match="no reading"):
        series().first_after(datetime(2024, 7, 1))


def test_bracketing_a_span_opens_with_the_reading_that_stood() -> None:
    span = Span(datetime(2024, 6, 5), datetime(2024, 6, 12))
    bracketed = series().bracketing(span)
    assert [item.taken_at.day for item in bracketed] == [4, 9]


def test_an_empty_series_says_so() -> None:
    assert ReadingSeries(WEIR).is_empty
    assert not series().is_empty
