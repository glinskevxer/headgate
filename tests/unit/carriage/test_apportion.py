from decimal import Decimal

import pytest

from headgate.carriage.apportion import (
    LossPolicy,
    apportion,
    carriage_summary,
    expected_loss,
    measured_loss,
    unexplained_loss,
)
from headgate.errors import PolicyError, ValidationError
from headgate.ids import DitchCode, TurnoutCode
from headgate.model.ditch import Ditch, DitchSystem, Turnout

NEAR = TurnoutCode("MAIN-3")
FAR = TurnoutCode("L2-20")
MIDDLE = TurnoutCode("L2-14")


def turnout(code: str, station: str) -> Turnout:
    return Turnout(
        code=TurnoutCode(code),
        name=f"{code} headgate",
        station_feet=Decimal(station),
        capacity_cfs=Decimal("6"),
        served_acres=Decimal("40"),
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
        loss_fraction_per_mile=Decimal("0.05"),
        turnouts=(turnout("L2-14", "5280"), turnout("L2-20", "10560")),
        parent=DitchCode("MAIN"),
        offtake_station_feet=Decimal("15840"),
    )
    return DitchSystem(ditches=(main, lateral))


def delivered() -> dict[TurnoutCode, Decimal]:
    return {NEAR: Decimal("100"), MIDDLE: Decimal("100"), FAR: Decimal("100")}


def test_charging_by_delivery_splits_evenly_when_deliveries_match() -> None:
    result = apportion(delivered(), Decimal("30"), LossPolicy.BY_DELIVERY)
    assert result.for_turnout(NEAR).loss_af == Decimal("10")
    assert result.total_loss_af == Decimal("30")


def test_charging_by_delivery_follows_the_volumes() -> None:
    taken = {NEAR: Decimal("300"), FAR: Decimal("100")}
    result = apportion(taken, Decimal("40"), LossPolicy.BY_DELIVERY)
    assert result.for_turnout(NEAR).loss_af == Decimal("30")
    assert result.for_turnout(FAR).loss_af == Decimal("10")


def test_charging_by_leg_costs_the_far_turnout_more() -> None:
    result = apportion(delivered(), Decimal("30"), LossPolicy.BY_LEG, system=system())
    assert result.for_turnout(FAR).loss_af > result.for_turnout(NEAR).loss_af
    assert result.total_loss_af == Decimal("30")


def test_charging_by_share_ignores_what_was_delivered() -> None:
    shares = {NEAR: Decimal("1"), MIDDLE: Decimal("1"), FAR: Decimal("4")}
    result = apportion(delivered(), Decimal("30"), LossPolicy.BY_SHARE, shares=shares)
    assert result.for_turnout(FAR).loss_af == Decimal("20")


def test_the_pieces_always_add_back_to_the_loss() -> None:
    taken = {NEAR: Decimal("1"), MIDDLE: Decimal("1"), FAR: Decimal("1")}
    result = apportion(taken, Decimal("10"), LossPolicy.BY_DELIVERY)
    assert result.total_loss_af == Decimal("10")


def test_a_charge_reports_what_had_to_be_diverted() -> None:
    result = apportion(delivered(), Decimal("30"), LossPolicy.BY_DELIVERY)
    assert result.for_turnout(NEAR).diverted_af == Decimal("110")
    assert result.total_delivered_af == Decimal("300")


def test_charging_by_share_without_shares_is_refused() -> None:
    with pytest.raises(PolicyError, match="needs the shares"):
        apportion(delivered(), Decimal("30"), LossPolicy.BY_SHARE)


def test_a_turnout_with_no_shares_recorded_is_refused() -> None:
    with pytest.raises(PolicyError, match="no shares are recorded"):
        apportion(delivered(), Decimal("30"), LossPolicy.BY_SHARE, shares={NEAR: Decimal("1")})


def test_charging_by_leg_without_the_ditch_is_refused() -> None:
    with pytest.raises(PolicyError, match="needs the ditch"):
        apportion(delivered(), Decimal("30"), LossPolicy.BY_LEG)


def test_a_negative_loss_is_refused() -> None:
    with pytest.raises(ValidationError, match="gained water"):
        apportion(delivered(), Decimal("-1"), LossPolicy.BY_DELIVERY)


def test_a_season_where_nothing_ran_has_nobody_to_charge() -> None:
    with pytest.raises(PolicyError, match="nobody to charge"):
        apportion({}, Decimal("30"), LossPolicy.BY_DELIVERY)


def test_turnouts_that_took_nothing_cannot_carry_the_loss() -> None:
    with pytest.raises(PolicyError, match="nothing to charge"):
        apportion({NEAR: Decimal("0")}, Decimal("30"), LossPolicy.BY_DELIVERY)


def test_asking_about_a_turnout_that_did_not_run_is_refused() -> None:
    result = apportion({NEAR: Decimal("10")}, Decimal("1"), LossPolicy.BY_DELIVERY)
    with pytest.raises(PolicyError, match="not in this apportionment"):
        result.for_turnout(FAR)


def test_the_measured_loss_is_the_headgate_less_the_turnouts() -> None:
    assert measured_loss(Decimal("330"), delivered()) == Decimal("30")


def test_turnouts_cannot_take_more_than_the_headgate_passed() -> None:
    with pytest.raises(PolicyError, match="not possible"):
        measured_loss(Decimal("100"), delivered())


def test_the_expected_loss_comes_out_of_the_loss_rates() -> None:
    assert expected_loss(system(), delivered()) > Decimal("0")


def test_a_break_in_the_bank_shows_up_as_unexplained_loss() -> None:
    quiet = unexplained_loss(system(), Decimal("330"), delivered())
    leaking = unexplained_loss(system(), Decimal("400"), delivered())
    assert leaking > quiet


def test_a_summary_names_every_ditch_the_water_ran_down() -> None:
    line = carriage_summary(system(), FAR, Decimal("6"))
    assert "MAIN" in line
    assert "L2" in line
    assert "cfs in" in line
