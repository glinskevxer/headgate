from decimal import Decimal

import pytest

from headgate.errors import HeadOutOfRangeError, ValidationError
from headgate.rating.curve import RatingCurve
from headgate.rating.weir import (
    ContractedRectangularWeir,
    cipolletti,
    rectangular_suppressed,
    v_notch_ninety,
)


def test_a_cipolletti_scales_with_its_crest() -> None:
    three_foot = cipolletti(Decimal("3"))
    six_foot = cipolletti(Decimal("6"))
    assert three_foot.discharge_cfs(Decimal("0.5")) * 2 == six_foot.discharge_cfs(Decimal("0.5"))


def test_a_cipolletti_reads_the_handbook_number() -> None:
    assert cipolletti(Decimal("3")).discharge_cfs(Decimal("1")) == Decimal("10.101")


def test_a_narrow_weir_has_a_narrower_working_range() -> None:
    assert cipolletti(Decimal("3")).max_head_feet == Decimal("1.000")
    assert cipolletti(Decimal("6")).max_head_feet == Decimal("2.000")


def test_a_head_past_a_third_of_the_crest_is_out_of_range() -> None:
    with pytest.raises(HeadOutOfRangeError):
        cipolletti(Decimal("3")).discharge_cfs(Decimal("1.2"))


def test_the_same_head_is_fine_on_a_wider_weir() -> None:
    assert cipolletti(Decimal("6")).discharge_cfs(Decimal("1.2")) > 0


def test_a_weir_with_no_crest_is_not_a_weir() -> None:
    with pytest.raises(ValidationError, match="is not a weir"):
        cipolletti(Decimal("0"))


def test_a_suppressed_rectangular_weir_uses_the_francis_coefficient() -> None:
    assert rectangular_suppressed(Decimal("4")).discharge_cfs(Decimal("1")) == Decimal("13.320")


def test_a_v_notch_is_a_steeper_curve() -> None:
    notch = v_notch_ninety()
    assert notch.discharge_cfs(Decimal("0.5")) < notch.discharge_cfs(Decimal("1")) / Decimal("4")


def test_a_v_notch_works_low_and_stops_early() -> None:
    notch = v_notch_ninety()
    assert notch.min_head_feet == Decimal("0.1")
    with pytest.raises(HeadOutOfRangeError):
        notch.discharge_cfs(Decimal("1.3"))


def test_every_weir_rating_is_a_rating_curve() -> None:
    assert isinstance(cipolletti(Decimal("3")), RatingCurve)
    assert isinstance(v_notch_ninety(), RatingCurve)
    assert isinstance(ContractedRectangularWeir(Decimal("4")), RatingCurve)


def test_a_contracted_weir_loses_crest_as_the_head_rises() -> None:
    weir = ContractedRectangularWeir(Decimal("4"))
    assert weir.effective_crest_feet(Decimal("0.5")) == Decimal("3.9")
    assert weir.effective_crest_feet(Decimal("1.0")) == Decimal("3.8")


def test_a_contracted_weir_passes_less_than_a_suppressed_one() -> None:
    contracted = ContractedRectangularWeir(Decimal("4")).discharge_cfs(Decimal("1"))
    suppressed = rectangular_suppressed(Decimal("4")).discharge_cfs(Decimal("1"))
    assert contracted < suppressed


def test_one_end_contraction_costs_half_as_much() -> None:
    one = ContractedRectangularWeir(Decimal("4"), contractions=1)
    two = ContractedRectangularWeir(Decimal("4"), contractions=2)
    assert one.discharge_cfs(Decimal("1")) > two.discharge_cfs(Decimal("1"))
    assert one.effective_crest_feet(Decimal("1")) == Decimal("3.9")


def test_a_contracted_weir_refuses_a_head_outside_its_range() -> None:
    weir = ContractedRectangularWeir(Decimal("4"))
    with pytest.raises(HeadOutOfRangeError):
        weir.discharge_cfs(Decimal("0.1"))
    with pytest.raises(HeadOutOfRangeError):
        weir.discharge_cfs(Decimal("1.5"))


def test_a_weir_with_an_impossible_contraction_count_is_refused() -> None:
    with pytest.raises(ValidationError, match="one or two end contractions"):
        ContractedRectangularWeir(Decimal("4"), contractions=3)


def test_a_staff_offset_carries_into_the_contracted_rating() -> None:
    plain = ContractedRectangularWeir(Decimal("4"))
    offset = ContractedRectangularWeir(Decimal("4"), head_offset_feet=Decimal("0.03"))
    assert offset.discharge_cfs(Decimal("0.8")) > plain.discharge_cfs(Decimal("0.8"))


def test_a_contracted_weir_describes_itself() -> None:
    text = ContractedRectangularWeir(Decimal("4")).describe()
    assert "contracted rectangular weir" in text
    assert "2 end contractions" in text
