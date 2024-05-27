from datetime import datetime
from decimal import Decimal

import pytest

from headgate.errors import PolicyError, ValidationError
from headgate.ids import DitchCode, TurnoutCode
from headgate.model.ditch import Ditch, DitchSystem, Turnout
from headgate.rotation.plan import (
    RotationPlan,
    RunWindow,
    check_capacity,
    check_in_season,
    check_plan,
)
from headgate.wateryear import IrrigationSeason, Span

FIRST = TurnoutCode("L2-14")
SECOND = TurnoutCode("L2-20")


def turnout(code: str, station: str) -> Turnout:
    return Turnout(
        code=TurnoutCode(code),
        name=f"{code} headgate",
        station_feet=Decimal(station),
        capacity_cfs=Decimal("8"),
        served_acres=Decimal("40"),
    )


def system(lateral_capacity: str = "12") -> DitchSystem:
    main = Ditch(
        code=DitchCode("MAIN"),
        name="Sanpete Main Canal",
        capacity_cfs=Decimal("48"),
        length_feet=Decimal("26400"),
        loss_fraction_per_mile=Decimal("0.02"),
        diversion_mile=Decimal("28.4"),
    )
    lateral = Ditch(
        code=DitchCode("L2"),
        name="Second Lateral",
        capacity_cfs=Decimal(lateral_capacity),
        length_feet=Decimal("10560"),
        loss_fraction_per_mile=Decimal("0.05"),
        turnouts=(turnout("L2-14", "5280"), turnout("L2-20", "10560")),
        parent=DitchCode("MAIN"),
        offtake_station_feet=Decimal("15840"),
    )
    return DitchSystem(ditches=(main, lateral))


def window(turnout_code: TurnoutCode, first_day: int, last_day: int, rate: str) -> RunWindow:
    return RunWindow(
        turnout=turnout_code,
        span=Span(datetime(2025, 6, first_day, 6), datetime(2025, 6, last_day, 6)),
        rate_cfs=Decimal(rate),
    )


def plan() -> RotationPlan:
    return RotationPlan(
        water_year=2025,
        windows=(window(FIRST, 1, 4, "6"), window(SECOND, 4, 7, "6"), window(FIRST, 7, 9, "6")),
    )


def test_a_window_at_no_rate_is_not_a_window() -> None:
    with pytest.raises(ValidationError, match="runs at 0 cfs"):
        window(FIRST, 1, 4, "0")


def test_a_window_reports_its_hours_and_its_volume() -> None:
    run = window(FIRST, 1, 4, "6")
    assert run.hours == Decimal("72.00")
    assert run.volume_af > Decimal("0")


def test_a_window_is_running_between_its_ends() -> None:
    run = window(FIRST, 1, 4, "6")
    assert run.running_at(datetime(2025, 6, 2, 12))
    assert not run.running_at(datetime(2025, 6, 4, 6))


def test_the_plan_says_who_is_running_at_a_moment() -> None:
    running = plan().running_at(datetime(2025, 6, 5, 12))
    assert [item.turnout for item in running] == [SECOND]


def test_the_plan_reports_a_turnout_rate_at_a_moment() -> None:
    assert plan().rate_at(FIRST, datetime(2025, 6, 2, 12)) == Decimal("6")
    assert plan().rate_at(FIRST, datetime(2025, 6, 5, 12)) == Decimal("0")


def test_hours_and_volume_add_up_across_a_turnout_windows() -> None:
    assert plan().hours_for(FIRST) == Decimal("120.00")
    assert plan().volume_for(FIRST) > plan().volume_for(SECOND)


def test_the_turnouts_on_the_rotation_come_back_sorted() -> None:
    assert plan().turnouts == (FIRST, SECOND)


def test_the_plan_spans_from_the_first_window_to_the_last() -> None:
    span = plan().span
    assert span is not None
    assert span.start == datetime(2025, 6, 1, 6)
    assert span.end == datetime(2025, 6, 9, 6)


def test_an_empty_plan_spans_nothing() -> None:
    assert RotationPlan(water_year=2025).span is None


def test_a_window_can_be_added() -> None:
    bigger = plan().add(window(SECOND, 9, 11, "6"))
    assert len(bigger.windows) == 4


def test_a_curtailed_turnout_comes_off_the_rotation() -> None:
    trimmed = plan().drop(FIRST)
    assert trimmed.turnouts == (SECOND,)


def test_dropping_a_turnout_that_is_not_on_it_is_refused() -> None:
    with pytest.raises(PolicyError, match="not on this rotation"):
        plan().drop(TurnoutCode("L2-99"))


def test_a_plan_inside_the_season_passes() -> None:
    check_in_season(plan(), IrrigationSeason.default_for(2025))


def test_a_plan_that_runs_before_the_season_opens_is_refused() -> None:
    early = RotationPlan(water_year=2025, windows=(window(FIRST, 1, 4, "6"),))
    season = IrrigationSeason(2025, datetime(2025, 6, 15).date(), datetime(2025, 9, 15).date())
    with pytest.raises(PolicyError, match="outside the declared season"):
        check_in_season(early, season)


def test_a_plan_for_another_year_cannot_be_checked() -> None:
    with pytest.raises(PolicyError, match="cannot be checked against"):
        check_in_season(plan(), IrrigationSeason.default_for(2024))


def test_a_plan_inside_the_ditch_capacity_passes() -> None:
    check_capacity(plan(), system())


def test_two_turnouts_running_at_once_can_swamp_the_lateral() -> None:
    crowded = RotationPlan(
        water_year=2025,
        windows=(window(FIRST, 1, 4, "8"), window(SECOND, 1, 4, "8")),
    )
    with pytest.raises(PolicyError, match="into ditch L2"):
        check_capacity(crowded, system())


def test_the_same_flow_passes_on_a_bigger_lateral() -> None:
    crowded = RotationPlan(
        water_year=2025,
        windows=(window(FIRST, 1, 4, "8"), window(SECOND, 1, 4, "8")),
    )
    check_capacity(crowded, system(lateral_capacity="20"))


def test_both_checks_run_together() -> None:
    check_plan(plan(), system(), IrrigationSeason.default_for(2025))
