from dataclasses import replace
from decimal import Decimal

import pytest

from headgate.errors import NotFoundError, ValidationError
from headgate.ids import DitchCode, TurnoutCode
from headgate.model.ditch import Ditch, DitchSystem, Turnout


def turnout(code: str, station: str, capacity: str = "3", acres: str = "40") -> Turnout:
    return Turnout(
        code=TurnoutCode(code),
        name=f"{code} headgate",
        station_feet=Decimal(station),
        capacity_cfs=Decimal(capacity),
        served_acres=Decimal(acres),
    )


def system() -> DitchSystem:
    main = Ditch(
        code=DitchCode("MAIN"),
        name="Sanpete Main Canal",
        capacity_cfs=Decimal("48"),
        length_feet=Decimal("26400"),
        loss_fraction_per_mile=Decimal("0.02"),
        turnouts=(turnout("MAIN-3", "5280"),),
        diversion_mile=Decimal("28.4"),
    )
    lateral = Ditch(
        code=DitchCode("L2"),
        name="Second Lateral",
        capacity_cfs=Decimal("12"),
        length_feet=Decimal("10560"),
        loss_fraction_per_mile=Decimal("0.04"),
        turnouts=(turnout("L2-14", "5280"), turnout("L2-20", "9000")),
        parent=DitchCode("MAIN"),
        offtake_station_feet=Decimal("15840"),
    )
    sub = Ditch(
        code=DitchCode("S1"),
        name="Cotton Sublateral",
        capacity_cfs=Decimal("4"),
        length_feet=Decimal("3000"),
        loss_fraction_per_mile=Decimal("0.06"),
        turnouts=(turnout("S1-2", "1500", "1.5", "20"),),
        parent=DitchCode("L2"),
        offtake_station_feet=Decimal("2640"),
    )
    return DitchSystem(ditches=(main, lateral, sub))


def test_the_main_canal_heads_on_the_stream() -> None:
    assert system().main.code == DitchCode("MAIN")
    assert system().main.diversion_mile == Decimal("28.4")


def test_a_main_canal_without_a_diversion_is_refused() -> None:
    with pytest.raises(ValidationError, match="no stream and no parent"):
        Ditch(
            code=DitchCode("MAIN"),
            name="Nowhere Canal",
            capacity_cfs=Decimal("10"),
            length_feet=Decimal("100"),
            loss_fraction_per_mile=Decimal("0.01"),
        )


def test_a_lateral_must_say_where_it_leaves_its_parent() -> None:
    with pytest.raises(ValidationError, match="does not say where it leaves"):
        Ditch(
            code=DitchCode("L9"),
            name="Loose Lateral",
            capacity_cfs=Decimal("10"),
            length_feet=Decimal("100"),
            loss_fraction_per_mile=Decimal("0.01"),
            parent=DitchCode("MAIN"),
        )


def test_a_turnout_belongs_to_the_ditch_that_lists_it() -> None:
    with pytest.raises(ValidationError, match="is not on ditch"):
        Ditch(
            code=DitchCode("L2"),
            name="Second Lateral",
            capacity_cfs=Decimal("10"),
            length_feet=Decimal("5000"),
            loss_fraction_per_mile=Decimal("0.01"),
            turnouts=(turnout("L3-1", "100"),),
            parent=DitchCode("MAIN"),
            offtake_station_feet=Decimal("100"),
        )


def test_a_turnout_past_the_end_of_its_ditch_is_refused() -> None:
    with pytest.raises(ValidationError, match="feet long"):
        Ditch(
            code=DitchCode("L2"),
            name="Second Lateral",
            capacity_cfs=Decimal("10"),
            length_feet=Decimal("5000"),
            loss_fraction_per_mile=Decimal("0.01"),
            turnouts=(turnout("L2-1", "6000"),),
            parent=DitchCode("MAIN"),
            offtake_station_feet=Decimal("100"),
        )


def test_a_system_runs_exactly_one_main() -> None:
    main = system().main
    second = replace(main, code=DitchCode("OTHER"), turnouts=())
    with pytest.raises(ValidationError, match="one main canal"):
        DitchSystem(ditches=(main, second))


def test_a_lateral_off_a_missing_parent_is_refused() -> None:
    orphan = Ditch(
        code=DitchCode("L9"),
        name="Orphan",
        capacity_cfs=Decimal("4"),
        length_feet=Decimal("500"),
        loss_fraction_per_mile=Decimal("0.01"),
        parent=DitchCode("L7"),
        offtake_station_feet=Decimal("10"),
    )
    with pytest.raises(ValidationError, match="which is not here"):
        DitchSystem(ditches=(system().main, orphan))


def test_a_lateral_may_not_leave_past_the_end_of_its_parent() -> None:
    far = Ditch(
        code=DitchCode("L9"),
        name="Too Far",
        capacity_cfs=Decimal("4"),
        length_feet=Decimal("500"),
        loss_fraction_per_mile=Decimal("0.01"),
        parent=DitchCode("MAIN"),
        offtake_station_feet=Decimal("99999"),
    )
    with pytest.raises(ValidationError, match="past its"):
        DitchSystem(ditches=(system().main, far))


def test_turnouts_are_found_with_the_ditch_they_sit_on() -> None:
    ditch, gate = system().find_turnout(TurnoutCode("S1-2"))
    assert ditch.code == DitchCode("S1")
    assert gate.capacity_cfs == Decimal("1.5")


def test_an_unknown_turnout_is_reported_as_missing() -> None:
    with pytest.raises(NotFoundError, match="no turnout"):
        system().find_turnout(TurnoutCode("L2-99"))


def test_children_lists_the_laterals_off_a_ditch() -> None:
    assert [ditch.code for ditch in system().children(DitchCode("L2"))] == [DitchCode("S1")]


def test_every_turnout_on_the_system_is_listed() -> None:
    assert len(system().all_turnouts()) == 4


def test_the_path_to_a_turnout_walks_down_from_the_headgate() -> None:
    path = system().path_to(TurnoutCode("S1-2"))
    assert [ditch.code for ditch, _ in path] == [
        DitchCode("MAIN"),
        DitchCode("L2"),
        DitchCode("S1"),
    ]
    assert [feet for _, feet in path] == [Decimal("15840"), Decimal("2640"), Decimal("1500")]


def test_carriage_distance_is_the_whole_walk() -> None:
    assert system().carriage_feet(TurnoutCode("S1-2")) == Decimal("19980")


def test_a_turnout_on_the_main_is_carried_only_down_the_main() -> None:
    assert system().carriage_feet(TurnoutCode("MAIN-3")) == Decimal("5280")


def test_a_ditch_finds_its_own_turnout() -> None:
    assert system().main.turnout(TurnoutCode("MAIN-3")).name == "MAIN-3 headgate"
    with pytest.raises(NotFoundError):
        system().main.turnout(TurnoutCode("MAIN-9"))
