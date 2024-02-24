from decimal import Decimal

import pytest

from headgate.errors import HeadOutOfRangeError, ValidationError
from headgate.rating.curve import PowerCurve, RatingCurve


def curve(**overrides: object) -> PowerCurve:
    fields: dict[str, object] = {
        "coefficient": Decimal("3.367"),
        "exponent": Decimal("1.5"),
        "low_head_feet": Decimal("0.05"),
        "high_head_feet": Decimal("2.0"),
        "label": "three foot Cipolletti",
    }
    fields.update(overrides)
    return PowerCurve(**fields)  # type: ignore[arg-type]


def test_a_power_curve_is_a_rating_curve() -> None:
    assert isinstance(curve(), RatingCurve)


def test_discharge_follows_the_power_law() -> None:
    assert curve().discharge_cfs(Decimal("1")) == Decimal("3.367")
    assert curve().discharge_cfs(Decimal("0.25")) == Decimal("0.421")


def test_a_head_offset_shifts_the_effective_head() -> None:
    shifted = curve(head_offset_feet=Decimal("0.02"))
    assert shifted.effective_head(Decimal("0.5")) == Decimal("0.52")
    assert shifted.discharge_cfs(Decimal("0.5")) > curve().discharge_cfs(Decimal("0.5"))


def test_reading_past_the_range_says_so() -> None:
    with pytest.raises(HeadOutOfRangeError, match="outside the rated range"):
        curve().discharge_cfs(Decimal("2.5"))


def test_reading_below_the_range_says_so_too() -> None:
    with pytest.raises(HeadOutOfRangeError) as caught:
        curve().discharge_cfs(Decimal("0.01"))
    assert caught.value.low == Decimal("0.05")


def test_the_curve_covers_its_own_ends() -> None:
    assert curve().covers(Decimal("0.05"))
    assert curve().covers(Decimal("2.0"))
    assert not curve().covers(Decimal("2.001"))


def test_the_inverse_finds_the_head_for_a_flow() -> None:
    assert curve().head_for(Decimal("3.367")) == Decimal("1.000")


def test_the_inverse_round_trips_within_a_thousandth() -> None:
    head = curve().head_for(Decimal("1.2"))
    assert abs(curve().discharge_cfs(head) - Decimal("1.2")) <= Decimal("0.005")


def test_asking_for_no_water_is_refused() -> None:
    with pytest.raises(ValidationError, match="not set by asking"):
        curve().head_for(Decimal("0"))


def test_asking_for_more_than_the_structure_passes_is_refused() -> None:
    with pytest.raises(HeadOutOfRangeError):
        curve().head_for(Decimal("40"))


def test_capacity_is_the_flow_at_the_top_of_the_range() -> None:
    assert curve().capacity_cfs() == curve().discharge_cfs(Decimal("2.0"))


def test_a_curve_needs_a_positive_coefficient_and_exponent() -> None:
    with pytest.raises(ValidationError, match="coefficient"):
        curve(coefficient=Decimal("0"))
    with pytest.raises(ValidationError, match="exponent"):
        curve(exponent=Decimal("0"))


def test_a_curve_needs_a_range() -> None:
    with pytest.raises(ValidationError, match="no range of head"):
        curve(low_head_feet=Decimal("2"), high_head_feet=Decimal("1"))


def test_an_offset_that_swamps_the_low_end_is_refused() -> None:
    with pytest.raises(ValidationError, match="zero effective head"):
        curve(head_offset_feet=Decimal("-0.05"))


def test_a_curve_describes_itself_for_the_field_book() -> None:
    text = curve(head_offset_feet=Decimal("0.02")).describe()
    assert "Q = 3.367 H^1.5" in text
    assert "staff offset" in text
    assert "0.05 to 2.0 ft" in text
