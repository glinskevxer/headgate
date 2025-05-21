from decimal import Decimal

import pytest

from headgate.duty.requirement import (
    REQUIREMENTS,
    MonthlyRequirement,
    gross_acre_feet,
    losses_to_application,
    net_acre_feet,
    net_inches,
    peak_rate_cfs,
    requirement_for,
)
from headgate.errors import ValidationError
from headgate.model.parcel import Application, CropCode


def test_every_crop_the_roll_carries_has_a_table() -> None:
    for crop in CropCode:
        assert crop in REQUIREMENTS


def test_a_table_covers_the_six_months_of_the_season() -> None:
    with pytest.raises(ValidationError, match="covers 3 months"):
        MonthlyRequirement(CropCode.ALFALFA, (Decimal("1"), Decimal("2"), Decimal("3")))


def test_a_table_may_not_have_a_negative_month() -> None:
    with pytest.raises(ValidationError, match="negative month"):
        MonthlyRequirement(CropCode.ALFALFA, (Decimal("-1"),) + (Decimal("0"),) * 5)


def test_alfalfa_peaks_in_july() -> None:
    assert requirement_for(CropCode.ALFALFA).peak_month == 7


def test_small_grain_is_finished_by_september() -> None:
    assert net_inches(CropCode.SMALL_GRAIN, 9) == Decimal("0")
    assert net_inches(CropCode.SMALL_GRAIN, 6) > Decimal("0")


def test_a_month_outside_the_season_needs_nothing() -> None:
    assert net_inches(CropCode.ALFALFA, 1) == Decimal("0")


def test_the_season_total_adds_the_months_up() -> None:
    table = requirement_for(CropCode.ALFALFA)
    assert net_inches(CropCode.ALFALFA) == table.season_inches


def test_fallow_ground_needs_nothing_at_all() -> None:
    assert net_inches(CropCode.FALLOW) == Decimal("0")
    assert net_acre_feet(CropCode.FALLOW, Decimal("40")) == Decimal("0")


def test_inches_over_acres_come_out_in_acre_feet() -> None:
    assert net_acre_feet(CropCode.ALFALFA, Decimal("12"), 7) == Decimal("8.2000")


def test_negative_acres_are_refused() -> None:
    with pytest.raises(ValidationError, match="negative acres"):
        net_acre_feet(CropCode.ALFALFA, Decimal("-1"))


def test_flood_irrigation_needs_more_delivered_than_a_pivot() -> None:
    flooded = gross_acre_feet(CropCode.ALFALFA, Decimal("40"), Application.FLOOD)
    pivoted = gross_acre_feet(CropCode.ALFALFA, Decimal("40"), Application.PIVOT)
    assert flooded > pivoted
    assert pivoted > net_acre_feet(CropCode.ALFALFA, Decimal("40"))


def test_the_efficiencies_run_the_way_a_farmer_would_expect() -> None:
    assert Application.FLOOD.efficiency < Application.WHEEL_LINE.efficiency
    assert Application.WHEEL_LINE.efficiency < Application.PIVOT.efficiency
    assert Application.PIVOT.efficiency < Application.DRIP.efficiency


def test_the_peak_rate_is_reported_in_cubic_feet_a_second() -> None:
    rate = peak_rate_cfs(CropCode.ALFALFA, Decimal("40"), Application.FLOOD)
    assert rate > Decimal("0")
    assert rate < Decimal("5")


def test_the_peak_rate_can_be_asked_for_a_named_month() -> None:
    july = peak_rate_cfs(CropCode.ALFALFA, Decimal("40"), Application.FLOOD, 7)
    april = peak_rate_cfs(CropCode.ALFALFA, Decimal("40"), Application.FLOOD, 4)
    assert july > april


def test_the_losses_are_the_difference_between_gross_and_net() -> None:
    lost = losses_to_application(CropCode.ALFALFA, Decimal("40"), Application.FLOOD)
    gross = gross_acre_feet(CropCode.ALFALFA, Decimal("40"), Application.FLOOD)
    net = net_acre_feet(CropCode.ALFALFA, Decimal("40"))
    assert lost == gross - net


def test_a_more_efficient_method_throws_less_away() -> None:
    flood = losses_to_application(CropCode.ALFALFA, Decimal("40"), Application.FLOOD)
    drip = losses_to_application(CropCode.ALFALFA, Decimal("40"), Application.DRIP)
    assert drip < flood
