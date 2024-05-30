from datetime import datetime
from decimal import Decimal

import pytest

from headgate.errors import PolicyError, ValidationError
from headgate.ids import DitchCode, TurnoutCode
from headgate.model.ditch import Ditch, DitchSystem, Turnout
from headgate.rotation.build import (
    Turn,
    build_cycle,
    deliverable_rate,
    repeat_cycle,
    shares_served,
)

FIRST = TurnoutCode("L2-14")
SECOND = TurnoutCode("L2-20")
THIRD = TurnoutCode("L2-26")
START = datetime(2025, 7, 1, 6)


def turnout(code: str, station: str, capacity: str) -> Turnout:
    return Turnout(
        code=TurnoutCode(code),
        name=f"{code} headgate",
        station_feet=Decimal(station),
        capacity_cfs=Decimal(capacity),
        served_acres=Decimal("40"),
    )


def system() -> DitchSystem:
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
        capacity_cfs=Decimal("12"),
        length_feet=Decimal("14000"),
        loss_fraction_per_mile=Decimal("0.05"),
        turnouts=(
            turnout("L2-14", "5280", "10"),
            turnout("L2-20", "10560", "4"),
            turnout("L2-26", "13000", "10"),
        ),
        parent=DitchCode("MAIN"),
        offtake_station_feet=Decimal("15840"),
    )
    return DitchSystem(ditches=(main, lateral))


def turns() -> list[Turn]:
    return [
        Turn(FIRST, Decimal("12")),
        Turn(SECOND, Decimal("6")),
        Turn(THIRD, Decimal("6")),
    ]


def test_a_turn_needs_shares_behind_it() -> None:
    with pytest.raises(ValidationError, match="on no shares"):
        Turn(FIRST, Decimal("0"))


def test_the_cycle_splits_the_hours_by_shares() -> None:
    cycle = build_cycle(system(), 2025, turns(), Decimal("10"), START, Decimal("48"))
    assert cycle.plan.hours_for(FIRST) == Decimal("24.00")
    assert cycle.plan.hours_for(SECOND) == Decimal("12.00")


def test_the_windows_run_end_to_end() -> None:
    cycle = build_cycle(system(), 2025, turns(), Decimal("10"), START, Decimal("48"))
    windows = cycle.plan.windows
    assert windows[0].span.end == windows[1].span.start
    assert windows[1].span.end == windows[2].span.start


def test_only_one_turnout_runs_at_a_time() -> None:
    cycle = build_cycle(system(), 2025, turns(), Decimal("10"), START, Decimal("48"))
    assert len(cycle.plan.running_at(datetime(2025, 7, 1, 12))) == 1


def test_a_small_turnout_cannot_take_the_whole_stream() -> None:
    cycle = build_cycle(system(), 2025, turns(), Decimal("10"), START, Decimal("48"))
    rates = {window.turnout: window.rate_cfs for window in cycle.plan.windows}
    assert rates[SECOND] == Decimal("4")
    assert rates[FIRST] == Decimal("10")


def test_the_lateral_capacity_caps_the_rate() -> None:
    assert deliverable_rate(system(), FIRST, Decimal("40")) == Decimal("10")
    assert deliverable_rate(system(), THIRD, Decimal("40")) == Decimal("10")


def test_a_curtailed_turnout_is_skipped_and_its_hours_go_to_the_others() -> None:
    cycle = build_cycle(
        system(), 2025, turns(), Decimal("10"), START, Decimal("48"), curtailed=(SECOND,)
    )
    assert cycle.skipped == (SECOND,)
    assert SECOND not in cycle.served
    assert cycle.plan.hours_for(FIRST) == Decimal("32.00")


def test_a_set_shorter_than_the_minimum_is_left_off() -> None:
    small = [*turns(), Turn(TurnoutCode("L2-30"), Decimal("0.5"))]
    system_with_gate = system()
    ditch = system_with_gate.ditch(DitchCode("L2"))
    extended = Ditch(
        code=ditch.code,
        name=ditch.name,
        capacity_cfs=ditch.capacity_cfs,
        length_feet=ditch.length_feet,
        loss_fraction_per_mile=ditch.loss_fraction_per_mile,
        turnouts=(*ditch.turnouts, turnout("L2-30", "13500", "6")),
        parent=ditch.parent,
        offtake_station_feet=ditch.offtake_station_feet,
    )
    built = DitchSystem(ditches=(system_with_gate.main, extended))
    cycle = build_cycle(built, 2025, small, Decimal("10"), START, Decimal("48"))
    assert cycle.short_set == (TurnoutCode("L2-30"),)
    assert TurnoutCode("L2-30") not in cycle.served


def test_a_complete_cycle_says_so() -> None:
    cycle = build_cycle(system(), 2025, turns(), Decimal("10"), START, Decimal("48"))
    assert cycle.is_complete


def test_a_cycle_with_no_water_is_refused() -> None:
    with pytest.raises(PolicyError, match="no water to rotate"):
        build_cycle(system(), 2025, turns(), Decimal("0"), START, Decimal("48"))


def test_a_cycle_with_no_length_is_refused() -> None:
    with pytest.raises(ValidationError, match="longer than no time"):
        build_cycle(system(), 2025, turns(), Decimal("10"), START, Decimal("0"))


def test_a_cycle_nobody_asked_for_is_refused() -> None:
    with pytest.raises(PolicyError, match="nobody has asked"):
        build_cycle(system(), 2025, [], Decimal("10"), START, Decimal("48"))


def test_a_cycle_where_everybody_is_curtailed_serves_nobody() -> None:
    cycle = build_cycle(
        system(),
        2025,
        turns(),
        Decimal("10"),
        START,
        Decimal("48"),
        curtailed=(FIRST, SECOND, THIRD),
    )
    assert cycle.served == ()
    assert len(cycle.skipped) == 3


def test_repeating_a_cycle_lays_them_end_to_end() -> None:
    plan = repeat_cycle(system(), 2025, turns(), Decimal("10"), START, Decimal("48"), 3)
    assert len(plan.windows) == 9
    assert plan.hours_for(FIRST) == Decimal("72.00")


def test_a_rotation_runs_at_least_one_cycle() -> None:
    with pytest.raises(ValidationError, match="at least one cycle"):
        repeat_cycle(system(), 2025, turns(), Decimal("10"), START, Decimal("48"), 0)


def test_the_shares_that_got_a_set_are_reported() -> None:
    cycle = build_cycle(
        system(), 2025, turns(), Decimal("10"), START, Decimal("48"), curtailed=(SECOND,)
    )
    assert shares_served(cycle, turns()) == Decimal("18")
