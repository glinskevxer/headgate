from decimal import Decimal

import pytest

from headgate.errors import RatingError, ValidationError
from headgate.rating.curve import RatingCurve
from headgate.rating.orifice import ConstantHeadOrifice, SubmergedOrifice, velocity_head_fps


def test_velocity_follows_the_square_root_of_the_differential() -> None:
    assert velocity_head_fps(Decimal("0.25")).quantize(Decimal("0.001")) == Decimal("4.011")
    assert velocity_head_fps(Decimal("1")) > velocity_head_fps(Decimal("0.25"))


def test_no_differential_means_no_flow_to_compute() -> None:
    with pytest.raises(ValidationError, match="not passing water"):
        velocity_head_fps(Decimal("0"))


def test_a_submerged_orifice_reads_off_its_area_and_differential() -> None:
    orifice = SubmergedOrifice(Decimal("1"), Decimal("1"))
    assert orifice.area_sqft == Decimal("1")
    assert orifice.discharge_cfs(Decimal("0.25")) == Decimal("2.447")


def test_a_bigger_opening_passes_more() -> None:
    small = SubmergedOrifice(Decimal("1"), Decimal("0.5")).discharge_cfs(Decimal("0.25"))
    large = SubmergedOrifice(Decimal("2"), Decimal("0.5")).discharge_cfs(Decimal("0.25"))
    assert abs(large - small * 2) <= Decimal("0.001")


def test_an_orifice_needs_both_dimensions() -> None:
    with pytest.raises(ValidationError, match="width and a height"):
        SubmergedOrifice(Decimal("1"), Decimal("0"))


def test_an_unpublished_coefficient_is_refused() -> None:
    with pytest.raises(ValidationError, match="not one anybody publishes"):
        SubmergedOrifice(Decimal("1"), Decimal("1"), coefficient=Decimal("1.4"))


def test_a_differential_outside_the_rated_range_is_refused() -> None:
    orifice = SubmergedOrifice(Decimal("1"), Decimal("1"))
    with pytest.raises(RatingError, match="outside the range"):
        orifice.discharge_cfs(Decimal("0.01"))
    with pytest.raises(RatingError, match="outside the range"):
        orifice.discharge_cfs(Decimal("3"))


def test_the_differential_needed_for_a_flow_round_trips() -> None:
    orifice = SubmergedOrifice(Decimal("2"), Decimal("1"))
    differential = orifice.differential_for(Decimal("5"))
    assert abs(orifice.discharge_cfs(differential) - Decimal("5")) < Decimal("0.01")


def test_asking_an_orifice_for_nothing_is_refused() -> None:
    with pytest.raises(ValidationError, match="not set by asking"):
        SubmergedOrifice(Decimal("1"), Decimal("1")).differential_for(Decimal("0"))


def test_a_constant_head_orifice_is_linear_in_the_opening() -> None:
    gate = ConstantHeadOrifice(Decimal("2"))
    half = gate.discharge_cfs(Decimal("0.25"))
    full = gate.discharge_cfs(Decimal("0.5"))
    assert full == half * 2


def test_a_constant_head_orifice_holds_two_tenths_by_default() -> None:
    assert ConstantHeadOrifice(Decimal("2")).differential_feet == Decimal("0.2")


def test_the_opening_for_a_flow_round_trips() -> None:
    gate = ConstantHeadOrifice(Decimal("2"))
    opening = gate.opening_for(Decimal("2"))
    assert abs(gate.discharge_cfs(opening) - Decimal("2")) < Decimal("0.01")


def test_a_gate_opened_past_its_rating_is_refused() -> None:
    with pytest.raises(RatingError, match="rated for"):
        ConstantHeadOrifice(Decimal("2")).discharge_cfs(Decimal("2"))


def test_a_constant_head_orifice_needs_a_width_and_a_differential() -> None:
    with pytest.raises(ValidationError, match="gate width"):
        ConstantHeadOrifice(Decimal("0"))
    with pytest.raises(ValidationError, match="differential above zero"):
        ConstantHeadOrifice(Decimal("2"), differential_feet=Decimal("0"))


def test_asking_a_gate_for_nothing_is_refused() -> None:
    with pytest.raises(ValidationError, match="not set by asking"):
        ConstantHeadOrifice(Decimal("2")).opening_for(Decimal("-1"))


def test_both_orifices_are_rating_curves() -> None:
    assert isinstance(SubmergedOrifice(Decimal("1"), Decimal("1")), RatingCurve)
    assert isinstance(ConstantHeadOrifice(Decimal("2")), RatingCurve)


def test_orifices_describe_themselves() -> None:
    assert "submerged orifice" in SubmergedOrifice(Decimal("1"), Decimal("2")).describe()
    assert "constant head orifice" in ConstantHeadOrifice(Decimal("2")).describe()
