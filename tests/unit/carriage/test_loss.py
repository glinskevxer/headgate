from decimal import Decimal

import pytest

from headgate.carriage.loss import (
    capacity_check,
    carriage_for,
    carried_fraction,
    headgate_needed_for,
    loss_between,
)
from headgate.errors import PolicyError, ValidationError
from headgate.ids import DitchCode, TurnoutCode
from headgate.model.ditch import Ditch, DitchSystem, Turnout


def turnout(code: str, station: str, capacity: str = "6") -> Turnout:
    return Turnout(
        code=TurnoutCode(code),
        name=f"{code} headgate",
        station_feet=Decimal(station),
        capacity_cfs=Decimal(capacity),
        served_acres=Decimal("40"),
    )


def system(main_loss: str = "0.02", lateral_loss: str = "0.05") -> DitchSystem:
    main = Ditch(
        code=DitchCode("MAIN"),
        name="Sanpete Main Canal",
        capacity_cfs=Decimal("48"),
        length_feet=Decimal("26400"),
        loss_fraction_per_mile=Decimal(main_loss),
        turnouts=(turnout("MAIN-3", "5280"),),
        diversion_mile=Decimal("28.4"),
    )
    lateral = Ditch(
        code=DitchCode("L2"),
        name="Second Lateral",
        capacity_cfs=Decimal("12"),
        length_feet=Decimal("10560"),
        loss_fraction_per_mile=Decimal(lateral_loss),
        turnouts=(turnout("L2-14", "5280"), turnout("L2-20", "10560")),
        parent=DitchCode("MAIN"),
        offtake_station_feet=Decimal("15840"),
    )
    return DitchSystem(ditches=(main, lateral))


def test_a_turnout_on_the_main_loses_only_the_main_rate() -> None:
    assert carried_fraction(system(), TurnoutCode("MAIN-3")) == Decimal("0.98")


def test_a_turnout_down_a_lateral_loses_twice() -> None:
    fraction = carried_fraction(system(), TurnoutCode("L2-14"))
    assert fraction < Decimal("0.98")
    assert fraction == Decimal("0.94") * Decimal("0.95")


def test_the_far_turnout_loses_more_than_the_near_one() -> None:
    near = carried_fraction(system(), TurnoutCode("L2-14"))
    far = carried_fraction(system(), TurnoutCode("L2-20"))
    assert far < near


def test_a_carriage_reports_every_leg() -> None:
    carriage = carriage_for(system(), TurnoutCode("L2-14"), Decimal("10"))
    assert [leg.ditch.code for leg in carriage.legs] == [DitchCode("MAIN"), DitchCode("L2")]
    assert carriage.legs[0].entering_cfs == Decimal("10")
    assert carriage.legs[1].entering_cfs == carriage.legs[0].leaving_cfs


def test_the_loss_is_the_difference_between_the_ends() -> None:
    carriage = carriage_for(system(), TurnoutCode("L2-14"), Decimal("10"))
    assert carriage.lost_cfs == carriage.headgate_cfs - carriage.delivered_cfs
    assert carriage.lost_cfs > Decimal("0")


def test_each_leg_reports_what_it_kept() -> None:
    carriage = carriage_for(system(), TurnoutCode("L2-14"), Decimal("10"))
    assert carriage.legs[0].lost_cfs > Decimal("0")
    assert carriage.legs[0].carried_fraction == Decimal("0.94")


def test_running_nothing_loses_nothing() -> None:
    carriage = carriage_for(system(), TurnoutCode("L2-14"), Decimal("0"))
    assert carriage.delivered_cfs == Decimal("0")
    assert carriage.carried_fraction == Decimal("1")
    assert carriage.legs[0].carried_fraction == Decimal("1")


def test_a_negative_headgate_flow_is_refused() -> None:
    with pytest.raises(ValidationError, match="negative flow"):
        carriage_for(system(), TurnoutCode("L2-14"), Decimal("-1"))


def test_the_headgate_has_to_turn_in_more_than_is_delivered() -> None:
    needed = headgate_needed_for(system(), TurnoutCode("L2-14"), Decimal("4"))
    assert needed > Decimal("4")
    carriage = carriage_for(system(), TurnoutCode("L2-14"), needed)
    assert abs(carriage.delivered_cfs - Decimal("4")) < Decimal("0.01")


def test_a_negative_delivery_is_refused() -> None:
    with pytest.raises(ValidationError, match="may not be negative"):
        headgate_needed_for(system(), TurnoutCode("L2-14"), Decimal("-1"))


def test_a_long_unlined_ditch_loses_everything_before_the_end() -> None:
    hungry = DitchSystem(
        ditches=(
            Ditch(
                code=DitchCode("SAND"),
                name="Sand Ditch",
                capacity_cfs=Decimal("8"),
                length_feet=Decimal("31680"),
                loss_fraction_per_mile=Decimal("0.3"),
                turnouts=(turnout("SAND-9", "31680"),),
                diversion_mile=Decimal("26"),
            ),
        )
    )
    with pytest.raises(PolicyError, match="loses everything"):
        carried_fraction(hungry, TurnoutCode("SAND-9"))
    with pytest.raises(PolicyError, match="loses everything"):
        carriage_for(hungry, TurnoutCode("SAND-9"), Decimal("5"))


def test_the_loss_on_a_run_is_reported_on_its_own() -> None:
    assert loss_between(system(), TurnoutCode("L2-14"), Decimal("10")) > Decimal("0")


def test_a_flow_bigger_than_the_ditch_is_refused() -> None:
    with pytest.raises(PolicyError, match="more than ditch MAIN carries"):
        capacity_check(system(), TurnoutCode("L2-14"), Decimal("60"))


def test_a_flow_bigger_than_the_lateral_is_refused() -> None:
    with pytest.raises(PolicyError, match="more than ditch L2 carries"):
        capacity_check(system(), TurnoutCode("L2-14"), Decimal("20"))


def test_a_flow_bigger_than_the_turnout_is_refused() -> None:
    with pytest.raises(PolicyError, match="more than turnout"):
        capacity_check(system(), TurnoutCode("L2-14"), Decimal("11"))


def test_a_flow_the_whole_path_can_carry_passes() -> None:
    capacity_check(system(), TurnoutCode("L2-14"), Decimal("6"))
