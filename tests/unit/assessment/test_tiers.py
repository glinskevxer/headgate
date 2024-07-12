from decimal import Decimal

import pytest

from headgate.assessment.tiers import Band, RateSchedule, flat_schedule
from headgate.errors import PolicyError, ValidationError
from headgate.money import Money


def schedule(minimum: str = "0.00") -> RateSchedule:
    return RateSchedule(
        water_year=2025,
        per_share=Money.from_dollars("4.50"),
        bands=(
            Band(Decimal("50"), Money.from_dollars("2.00")),
            Band(Decimal("150"), Money.from_dollars("3.50")),
            Band(None, Money.from_dollars("6.00")),
        ),
        minimum_bill=Money.from_dollars(minimum),
    )


def test_a_band_needs_a_ceiling_above_nothing() -> None:
    with pytest.raises(ValidationError, match="is not a band"):
        Band(Decimal("0"), Money.from_dollars("2.00"))


def test_a_band_that_pays_the_shareholder_is_refused() -> None:
    with pytest.raises(ValidationError, match="not a rate"):
        Band(Decimal("50"), Money(-100))


def test_a_schedule_needs_bands() -> None:
    with pytest.raises(ValidationError, match="no bands"):
        RateSchedule(2025, Money.from_dollars("4.50"), ())


def test_a_schedule_needs_something_above_its_top_band() -> None:
    with pytest.raises(ValidationError, match="nothing above it"):
        RateSchedule(
            2025,
            Money.from_dollars("4.50"),
            (Band(Decimal("50"), Money.from_dollars("2.00")),),
        )


def test_bands_have_to_climb() -> None:
    with pytest.raises(ValidationError, match="which is not above"):
        RateSchedule(
            2025,
            Money.from_dollars("4.50"),
            (
                Band(Decimal("150"), Money.from_dollars("2.00")),
                Band(Decimal("50"), Money.from_dollars("3.50")),
                Band(None, Money.from_dollars("6.00")),
            ),
        )


def test_an_open_band_may_not_sit_in_the_middle() -> None:
    with pytest.raises(ValidationError, match="open band before the top"):
        RateSchedule(
            2025,
            Money.from_dollars("4.50"),
            (Band(None, Money.from_dollars("2.00")), Band(None, Money.from_dollars("6.00"))),
        )


def test_a_share_charge_that_pays_the_holder_is_refused() -> None:
    with pytest.raises(ValidationError, match="not a charge"):
        RateSchedule(2025, Money(-450), (Band(None, Money.from_dollars("2.00")),))


def test_the_band_is_the_one_the_last_acre_foot_falls_in() -> None:
    assert schedule().band_for(Decimal("40")).rate_per_af == Money.from_dollars("2.00")
    assert schedule().band_for(Decimal("120")).rate_per_af == Money.from_dollars("3.50")
    assert schedule().band_for(Decimal("400")).rate_per_af == Money.from_dollars("6.00")


def test_a_negative_delivery_has_no_band() -> None:
    with pytest.raises(ValidationError, match="no band"):
        schedule().band_for(Decimal("-1"))


def test_water_is_charged_a_step_at_a_time() -> None:
    assert schedule().water_charge(Decimal("50")) == Money.from_dollars("100.00")
    assert schedule().water_charge(Decimal("100")) == Money.from_dollars("275.00")


def test_the_top_band_carries_everything_above_it() -> None:
    charged = schedule().water_charge(Decimal("200"))
    assert charged == Money.from_dollars("750.00")


def test_no_water_is_charged_nothing() -> None:
    assert schedule().water_charge(Decimal("0")) == Money.zero()


def test_a_negative_delivery_cannot_be_charged() -> None:
    with pytest.raises(ValidationError, match="cannot be charged"):
        schedule().water_charge(Decimal("-1"))


def test_shares_are_charged_flat() -> None:
    assert schedule().share_charge(Decimal("20")) == Money.from_dollars("90.00")


def test_a_negative_shareholding_is_refused() -> None:
    with pytest.raises(ValidationError, match="not a shareholding"):
        schedule().share_charge(Decimal("-1"))


def test_a_bill_adds_the_shares_and_the_water() -> None:
    assert schedule().bill_for(Decimal("20"), Decimal("50")) == Money.from_dollars("190.00")


def test_a_small_bill_is_lifted_to_the_minimum() -> None:
    assert schedule("75.00").bill_for(Decimal("1"), Decimal("0")) == Money.from_dollars("75.00")


def test_a_bill_over_the_minimum_is_left_alone() -> None:
    assert schedule("75.00").bill_for(Decimal("20"), Decimal("50")) == Money.from_dollars("190.00")


def test_the_top_of_the_schedule_is_the_last_ceiling() -> None:
    assert schedule().top_of_the_schedule == Decimal("150")


def test_a_flat_schedule_charges_one_rate_all_the_way_up() -> None:
    flat = flat_schedule(2025, Money.from_dollars("4.50"), Money.from_dollars("3.00"))
    assert flat.water_charge(Decimal("200")) == Money.from_dollars("600.00")
    assert flat.top_of_the_schedule is None


def test_a_band_above_the_top_cannot_happen_on_a_valid_schedule() -> None:
    closed = RateSchedule.__new__(RateSchedule)
    object.__setattr__(closed, "water_year", 2025)
    object.__setattr__(closed, "per_share", Money.zero())
    object.__setattr__(closed, "bands", (Band(Decimal("10"), Money.from_dollars("1.00")),))
    object.__setattr__(closed, "minimum_bill", Money.zero())
    with pytest.raises(PolicyError, match="above the top band"):
        closed.band_for(Decimal("40"))
