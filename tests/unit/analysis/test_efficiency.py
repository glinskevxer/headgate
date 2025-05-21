from datetime import date
from decimal import Decimal

import pytest

from headgate.analysis.efficiency import DutyReview, TurnoutDuty, review
from headgate.errors import PolicyError, ValidationError
from headgate.ids import AccountNumber, TurnoutCode
from headgate.model.parcel import Application, CropCode, Parcel, PlaceOfUse

NEAR = TurnoutCode("L2-14")
FAR = TurnoutCode("L2-20")
SEASON = date(2025, 6, 1)


def place(application: Application = Application.FLOOD) -> PlaceOfUse:
    return PlaceOfUse(
        parcels=(
            Parcel(
                "11-042-001", AccountNumber(118), NEAR, Decimal("40"), CropCode.ALFALFA, application
            ),
            Parcel(
                "11-042-002", AccountNumber(212), FAR, Decimal("20"), CropCode.PASTURE, application
            ),
        )
    )


def duty_review(near: str, far: str) -> DutyReview:
    return review(2025, place(), {NEAR: Decimal(near), FAR: Decimal(far)}, SEASON)


def test_a_turnout_carries_its_ground_and_its_water() -> None:
    found = duty_review("200", "80").for_turnout(NEAR)
    assert found.acres == Decimal("40")
    assert found.required_af > Decimal("0")
    assert found.delivered_af == Decimal("200")


def test_a_turnout_about_right_is_neither_short_nor_over() -> None:
    found = duty_review("200", "80")
    near = found.for_turnout(NEAR)
    matched = duty_review(str(near.required_af), "80").for_turnout(NEAR)
    assert not matched.is_short
    assert not matched.is_generous


def test_a_turnout_well_under_its_requirement_is_short() -> None:
    found = duty_review("20", "80").for_turnout(NEAR)
    assert found.is_short
    assert found.shortfall_af > Decimal("0")
    assert "short" in found.describe()


def test_a_turnout_well_over_its_requirement_is_generous() -> None:
    found = duty_review("2000", "80").for_turnout(NEAR)
    assert found.is_generous
    assert found.shortfall_af == Decimal("0")
    assert "over" in found.describe()


def test_the_applied_depth_is_reported_in_inches() -> None:
    found = duty_review("40", "80").for_turnout(NEAR)
    assert found.depth_inches == Decimal("12.00")


def test_a_turnout_with_no_ground_reports_nothing_required() -> None:
    empty = TurnoutDuty(NEAR, Decimal("0"), Decimal("0"), Decimal("10"))
    assert empty.ratio == Decimal("0")
    assert empty.depth_inches == Decimal("0")
    assert not empty.is_short
    assert "irrigated nothing" in empty.describe()


def test_the_review_totals_the_district() -> None:
    found = duty_review("200", "80")
    assert found.required_af > Decimal("0")
    assert found.delivered_af == Decimal("280")
    assert found.ratio > Decimal("0")


def test_the_short_and_generous_turnouts_are_listed() -> None:
    found = duty_review("20", "2000")
    assert [item.turnout for item in found.short] == [NEAR]
    assert [item.turnout for item in found.generous] == [FAR]


def test_a_turnout_that_took_water_with_no_ground_behind_it_is_included() -> None:
    found = review(2025, PlaceOfUse(parcels=()), {NEAR: Decimal("40")}, SEASON)
    assert found.for_turnout(NEAR).required_af == Decimal("0")
    assert found.ratio == Decimal("0")


def test_a_more_efficient_method_needs_less_water() -> None:
    flood = review(2025, place(Application.FLOOD), {NEAR: Decimal("200")}, SEASON)
    pivot = review(2025, place(Application.PIVOT), {NEAR: Decimal("200")}, SEASON)
    assert pivot.required_af < flood.required_af


def test_a_turnout_not_in_the_review_is_refused() -> None:
    with pytest.raises(PolicyError, match="not in this review"):
        duty_review("200", "80").for_turnout(TurnoutCode("L2-99"))


def test_a_review_needs_a_day_to_work_as_of() -> None:
    with pytest.raises(ValidationError, match="as of a day"):
        review(2025, place(), {}, "the summer")


def test_the_summary_carries_the_ratio() -> None:
    summary = dict(duty_review("200", "80").summary())
    assert summary["water year"] == "2025"
    assert "acre feet" in summary["required"]
