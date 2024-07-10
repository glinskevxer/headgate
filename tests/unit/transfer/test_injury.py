from datetime import date
from decimal import Decimal

import pytest

from headgate.errors import PolicyError, ValidationError
from headgate.ids import DecreeNumber
from headgate.model.parcel import CropCode
from headgate.model.right import Priority, RightKind, RightStatus, WaterRight
from headgate.transfer.injury import (
    monthly_pattern,
    require_no_injury,
    review,
    rights_in_reach,
)


def right(sequence: int, mile: str, status: RightStatus = RightStatus.DECREED) -> WaterRight:
    return WaterRight(
        decree=DecreeNumber(f"CDA-1920-{sequence}"),
        owner=f"Owner {sequence}",
        kind=RightKind.DIRECT_FLOW,
        priority=Priority(date(1890, 5, 1), 1920, sequence),
        diversion_mile=Decimal(mile),
        rate_cfs=Decimal("2"),
        status=status,
    )


def test_a_pattern_follows_the_crop_and_adds_back_to_the_total() -> None:
    pattern = monthly_pattern(Decimal("60"), CropCode.ALFALFA)
    assert sum(pattern.values(), Decimal("0")) == Decimal("60")
    assert pattern[7] > pattern[4]


def test_a_pattern_from_nothing_is_all_zeroes() -> None:
    pattern = monthly_pattern(Decimal("0"), CropCode.ALFALFA)
    assert set(pattern.values()) == {Decimal("0")}


def test_a_negative_consumption_has_no_pattern() -> None:
    with pytest.raises(ValidationError, match="negative volume"):
        monthly_pattern(Decimal("-1"), CropCode.ALFALFA)


def test_fallow_ground_has_no_pattern_at_all() -> None:
    with pytest.raises(PolicyError, match="no water in any month"):
        monthly_pattern(Decimal("60"), CropCode.FALLOW)


def test_moving_the_same_crop_injures_nobody() -> None:
    pattern = monthly_pattern(Decimal("60"), CropCode.ALFALFA)
    found = review(pattern, pattern)
    assert not found.injures
    assert found.reasons == ()


def test_moving_to_a_thirstier_month_injures() -> None:
    before = monthly_pattern(Decimal("60"), CropCode.SMALL_GRAIN)
    after = monthly_pattern(Decimal("60"), CropCode.CORN)
    found = review(before, after)
    assert found.injures
    assert found.injures_by_quantity
    assert "acre feet more than it used to" in found.reasons[0]


def test_the_worst_month_is_named() -> None:
    before = monthly_pattern(Decimal("60"), CropCode.SMALL_GRAIN)
    after = monthly_pattern(Decimal("60"), CropCode.CORN)
    worst = review(before, after).worst_month
    assert worst is not None
    assert worst.month in (7, 8)


def test_a_change_inside_the_tolerance_is_not_an_injury() -> None:
    before = monthly_pattern(Decimal("60"), CropCode.ALFALFA)
    after = dict(before)
    after[7] = after[7] + Decimal("0.4")
    assert not review(before, after).injures


def test_a_review_with_no_months_has_no_worst_month() -> None:
    assert review({}, {}).worst_month is None


def test_moving_a_headgate_upstream_passes_the_rights_in_between() -> None:
    rights = [right(4, "18"), right(5, "24"), right(6, "34")]
    assert rights_in_reach(rights, Decimal("14"), Decimal("28")) == (
        DecreeNumber("CDA-1920-4"),
        DecreeNumber("CDA-1920-5"),
    )


def test_moving_a_headgate_downstream_passes_nobody() -> None:
    rights = [right(4, "18")]
    assert rights_in_reach(rights, Decimal("28"), Decimal("14")) == ()


def test_an_abandoned_right_in_the_reach_is_not_injured() -> None:
    rights = [right(4, "18", RightStatus.ABANDONED)]
    assert rights_in_reach(rights, Decimal("14"), Decimal("28")) == ()


def test_a_move_above_another_right_injures_it() -> None:
    pattern = monthly_pattern(Decimal("60"), CropCode.ALFALFA)
    found = review(
        pattern,
        pattern,
        rights=[right(4, "18")],
        from_mile=Decimal("14"),
        to_mile=Decimal("28"),
    )
    assert found.injures
    assert found.injures_by_reach
    assert "moves above" in found.reasons[0]


def test_return_flow_that_stops_coming_back_is_an_injury() -> None:
    pattern = monthly_pattern(Decimal("60"), CropCode.ALFALFA)
    found = review(pattern, pattern, return_flow_owed_af=Decimal("40"))
    assert found.injures_by_return_flow
    assert "return flow" in found.reasons[0]


def test_replacing_the_return_flow_answers_that_objection() -> None:
    pattern = monthly_pattern(Decimal("60"), CropCode.ALFALFA)
    found = review(
        pattern,
        pattern,
        return_flow_owed_af=Decimal("40"),
        return_flow_replaced_af=Decimal("40"),
    )
    assert not found.injures


def test_over_replacing_the_return_flow_is_not_a_credit() -> None:
    pattern = monthly_pattern(Decimal("60"), CropCode.ALFALFA)
    found = review(
        pattern,
        pattern,
        return_flow_owed_af=Decimal("10"),
        return_flow_replaced_af=Decimal("40"),
    )
    assert found.return_flow_shortfall_af == Decimal("0")


def test_every_failing_test_is_reported_not_just_the_first() -> None:
    before = monthly_pattern(Decimal("60"), CropCode.SMALL_GRAIN)
    after = monthly_pattern(Decimal("60"), CropCode.CORN)
    found = review(
        before,
        after,
        rights=[right(4, "18")],
        from_mile=Decimal("14"),
        to_mile=Decimal("28"),
        return_flow_owed_af=Decimal("40"),
    )
    assert len(found.reasons) == 3


def test_a_negative_tolerance_is_refused() -> None:
    with pytest.raises(ValidationError, match="may not be negative"):
        review({}, {}, tolerance_af=Decimal("-1"))


def test_a_caller_about_to_approve_insists_on_a_clean_review() -> None:
    pattern = monthly_pattern(Decimal("60"), CropCode.ALFALFA)
    clean = review(pattern, pattern)
    assert require_no_injury(clean) is clean
    dirty = review(pattern, pattern, return_flow_owed_af=Decimal("40"))
    with pytest.raises(PolicyError, match="would injure other rights"):
        require_no_injury(dirty)
