from datetime import date, datetime
from decimal import Decimal

import pytest

from headgate.errors import PolicyError, ValidationError
from headgate.ids import DeviceTag, TurnoutCode
from headgate.measure.recalibration import Rerating, material, restate
from headgate.model.device import Calibration, Device, DeviceKind
from headgate.model.reading import ReadingSeries, StaffReading
from headgate.wateryear import Span

TURNOUT = TurnoutCode("L2-14")
WEIR = DeviceTag("WEIR-L2-14")
SPRING = Calibration(date(2025, 4, 1), "R. Aldrich", date(2026, 4, 1), Decimal("0.02"))
EARLIER = Calibration(date(2024, 4, 1), "R. Aldrich", date(2025, 4, 1), Decimal("0"))


def device(calibrations: tuple[Calibration, ...] = (EARLIER, SPRING)) -> Device:
    return Device(
        tag=WEIR,
        kind=DeviceKind.CIPOLLETTI_WEIR,
        installed=date(2016, 3, 1),
        crest_width_feet=Decimal("3"),
        turnout=TURNOUT,
        calibrations=calibrations,
    )


def series() -> ReadingSeries:
    return ReadingSeries(
        WEIR,
        tuple(
            StaffReading(
                device=WEIR,
                taken_at=datetime(2025, 6, day, 6),
                observer="D. Yardley",
                head_feet=Decimal("0.60"),
            )
            for day in (1, 6, 11)
        ),
    )


def span() -> Span:
    return Span(datetime(2025, 6, 1, 6), datetime(2025, 6, 16, 6))


def rerating(offset: str = "0.00") -> Rerating:
    return Rerating(
        device=device(),
        corrected_offset_feet=Decimal(offset),
        found_on=date(2025, 9, 15),
        found_by="R. Aldrich",
        reason="the staff had been reading two hundredths high since spring",
    )


def test_a_rerating_says_who_found_it_and_why() -> None:
    with pytest.raises(ValidationError, match="says who found it"):
        Rerating(device(), Decimal("0"), date(2025, 9, 15), "  ", "because")
    with pytest.raises(ValidationError, match="says what was wrong"):
        Rerating(device(), Decimal("0"), date(2025, 9, 15), "R. Aldrich", "   ")


def test_an_offset_that_means_a_reset_staff_is_refused() -> None:
    with pytest.raises(ValidationError, match="staff was reset"):
        rerating("0.75")


def test_a_rerating_reaches_back_to_the_check_it_corrects() -> None:
    assert rerating().reaches_back_to == date(2025, 4, 1)
    assert rerating().offset_change == Decimal("-0.02")
    assert rerating().changes_anything


def test_a_rerating_that_changes_nothing_says_so() -> None:
    assert not rerating("0.02").changes_anything


def test_a_device_with_no_check_standing_cannot_be_rerated() -> None:
    bare = Rerating(
        device=device(calibrations=()),
        corrected_offset_feet=Decimal("0"),
        found_on=date(2025, 9, 15),
        found_by="R. Aldrich",
        reason="nothing to correct",
    )
    with pytest.raises(PolicyError, match="nothing to re-rate"):
        _ = bare.standing_check


def test_the_corrected_device_reads_lower() -> None:
    corrected = rerating().corrected_device()
    assert corrected.staff_offset_on(date(2025, 6, 1)) == Decimal("0.00")
    assert device().staff_offset_on(date(2025, 6, 1)) == Decimal("0.02")


def test_the_earlier_check_is_left_alone() -> None:
    corrected = rerating().corrected_device()
    assert corrected.staff_offset_on(date(2024, 6, 1)) == Decimal("0")
    assert len(corrected.calibrations) == 2


def test_restating_shows_both_records_and_the_difference() -> None:
    found = restate(rerating(), TURNOUT, series(), span())
    assert found.before.total_af > found.after.total_af
    assert found.is_a_credit
    assert found.change_af < Decimal("0")
    assert found.percent_change < Decimal("0")


def test_a_restatement_describes_itself_for_the_file() -> None:
    text = restate(rerating(), TURNOUT, series(), span()).describe()
    assert "L2-14 delivered" in text
    assert "less than the book says" in text
    assert "reading two hundredths high" in text


def test_a_span_outside_the_check_cannot_be_restated() -> None:
    winter = Span(datetime(2024, 6, 1, 6), datetime(2024, 6, 16, 6))
    with pytest.raises(PolicyError, match="covers to"):
        restate(rerating(), TURNOUT, series(), winter)


def test_a_correction_the_other_way_credits_more_water() -> None:
    found = restate(rerating("0.05"), TURNOUT, series(), span())
    assert not found.is_a_credit
    assert found.change_af > Decimal("0")


def test_a_small_change_is_not_worth_restating_a_season_over() -> None:
    found = restate(rerating("0.019"), TURNOUT, series(), span())
    assert not material(found)
    assert material(found, threshold_af=Decimal("0"))


def test_a_big_change_is_material() -> None:
    assert material(restate(rerating("0.20"), TURNOUT, series(), span()))


def test_a_negative_threshold_is_refused() -> None:
    found = restate(rerating(), TURNOUT, series(), span())
    with pytest.raises(ValidationError, match="may not be negative"):
        material(found, threshold_af=Decimal("-1"))
