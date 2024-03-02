from decimal import Decimal

import pytest

from headgate.errors import HeadOutOfRangeError, SubmergedFlowError, ValidationError
from headgate.rating.curve import RatingCurve
from headgate.rating.flume import CutthroatFlume, ParshallFlume


def test_a_one_foot_parshall_reads_the_handbook_number() -> None:
    assert ParshallFlume(Decimal("1")).discharge_cfs(Decimal("1")) == Decimal("4.000")


def test_a_wider_parshall_passes_more_at_the_same_head() -> None:
    narrow = ParshallFlume(Decimal("1")).discharge_cfs(Decimal("0.8"))
    wide = ParshallFlume(Decimal("3")).discharge_cfs(Decimal("0.8"))
    assert wide > narrow * 2


def test_the_parshall_exponent_creeps_up_with_the_throat() -> None:
    assert ParshallFlume(Decimal("1")).exponent == Decimal("1.522")
    assert ParshallFlume(Decimal("4")).exponent > Decimal("1.522")


def test_a_flume_with_no_throat_is_refused() -> None:
    with pytest.raises(ValidationError, match="is not a flume"):
        ParshallFlume(Decimal("0"))


def test_a_flume_wider_than_the_district_owns_is_refused() -> None:
    with pytest.raises(ValidationError, match="eight feet"):
        ParshallFlume(Decimal("10"))


def test_a_head_past_the_rated_range_is_refused() -> None:
    with pytest.raises(HeadOutOfRangeError):
        ParshallFlume(Decimal("1")).discharge_cfs(Decimal("2"))


def test_a_narrow_flume_drowns_sooner_than_a_wide_one() -> None:
    assert ParshallFlume(Decimal("1")).submergence_limit == Decimal("0.6")
    assert ParshallFlume(Decimal("3")).submergence_limit == Decimal("0.7")


def test_submergence_is_the_ratio_of_the_two_heads() -> None:
    flume = ParshallFlume(Decimal("2"))
    assert flume.submergence(Decimal("1.0"), Decimal("0.5")) == Decimal("0.500")
    assert not flume.is_submerged(Decimal("1.0"), Decimal("0.5"))
    assert flume.is_submerged(Decimal("1.0"), Decimal("0.85"))


def test_a_drowned_flume_measures_nothing() -> None:
    flume = ParshallFlume(Decimal("1"))
    with pytest.raises(SubmergedFlowError, match="past the free flow limit"):
        flume.discharge_with_tailwater(Decimal("1.0"), Decimal("0.8"))


def test_the_same_tailwater_is_fine_on_a_wider_flume() -> None:
    wide = ParshallFlume(Decimal("3"))
    assert wide.discharge_with_tailwater(Decimal("1.0"), Decimal("0.65")) > 0


def test_a_flume_with_no_upstream_head_is_not_passing_water() -> None:
    with pytest.raises(ValidationError, match="not passing water"):
        ParshallFlume(Decimal("1")).submergence(Decimal("0"), Decimal("0"))


def test_a_negative_tailwater_reading_is_refused() -> None:
    with pytest.raises(ValidationError, match="may not be negative"):
        ParshallFlume(Decimal("1")).submergence(Decimal("1"), Decimal("-0.1"))


def test_a_cutthroat_is_rated_on_its_own_coefficient() -> None:
    flume = CutthroatFlume(Decimal("1"))
    assert flume.coefficient == Decimal("4.50")
    assert flume.discharge_cfs(Decimal("1")) == Decimal("4.500")


def test_a_cutthroat_drowns_between_the_two_parshall_limits() -> None:
    assert CutthroatFlume(Decimal("2")).submergence_limit == Decimal("0.65")


def test_a_cutthroat_with_no_throat_is_refused() -> None:
    with pytest.raises(ValidationError, match="is not a flume"):
        CutthroatFlume(Decimal("-1"))


def test_a_cutthroat_refuses_a_head_past_its_range() -> None:
    with pytest.raises(HeadOutOfRangeError):
        CutthroatFlume(Decimal("1")).discharge_cfs(Decimal("1.5"))


def test_both_flumes_are_rating_curves() -> None:
    assert isinstance(ParshallFlume(Decimal("1")), RatingCurve)
    assert isinstance(CutthroatFlume(Decimal("1")), RatingCurve)


def test_flumes_describe_themselves() -> None:
    assert "Parshall" in ParshallFlume(Decimal("2")).describe()
    assert "cutthroat" in CutthroatFlume(Decimal("2")).describe()


def test_a_staff_offset_raises_the_reading() -> None:
    plain = ParshallFlume(Decimal("2"))
    offset = ParshallFlume(Decimal("2"), head_offset_feet=Decimal("0.02"))
    assert offset.discharge_cfs(Decimal("0.9")) > plain.discharge_cfs(Decimal("0.9"))
