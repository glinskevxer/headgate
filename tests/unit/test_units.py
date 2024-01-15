from decimal import Decimal

import pytest

from headgate.errors import ValidationError
from headgate.units import (
    ACRE_FEET_PER_CFS_DAY,
    MinersInchStandard,
    acre_feet_to_cfs,
    cfs_days,
    cfs_for_seconds,
    cfs_to_miners_inches,
    check_rate,
    check_volume,
    depth_over_acres,
    gpm_to_cfs,
    miners_inches_to_cfs,
    round_rate,
    round_volume,
)


def test_one_cfs_for_a_day_is_the_familiar_constant() -> None:
    assert cfs_days(Decimal("1"), Decimal("1")) == Decimal("1.9835")
    assert Decimal("1.98") < ACRE_FEET_PER_CFS_DAY < Decimal("1.99")


def test_cfs_for_seconds_matches_cfs_days() -> None:
    assert cfs_for_seconds(Decimal("2.5"), Decimal("86400")) == cfs_days(
        Decimal("2.5"), Decimal("1")
    )


def test_volume_and_rate_round_at_their_own_places() -> None:
    assert round_volume(Decimal("1.00005")) == Decimal("1.0001")
    assert round_rate(Decimal("1.2345")) == Decimal("1.235")


def test_acre_feet_back_to_a_rate_round_trips_within_rounding() -> None:
    rate = acre_feet_to_cfs(Decimal("1.9835"), Decimal("86400"))
    assert rate == Decimal("1.000")


def test_a_negative_rate_is_refused() -> None:
    with pytest.raises(ValidationError, match="may not be negative"):
        check_rate(Decimal("-0.1"))


def test_an_absurd_rate_is_refused() -> None:
    with pytest.raises(ValidationError, match="larger than any ditch"):
        check_rate(Decimal("10001"))


def test_a_negative_volume_is_refused() -> None:
    with pytest.raises(ValidationError, match="may not be negative"):
        check_volume(Decimal("-0.0001"))


def test_a_negative_duration_is_refused() -> None:
    with pytest.raises(ValidationError, match="duration may not be negative"):
        cfs_for_seconds(Decimal("1"), Decimal("-1"))


def test_spreading_a_volume_over_no_time_is_refused() -> None:
    with pytest.raises(ValidationError, match="no time"):
        acre_feet_to_cfs(Decimal("1"), Decimal("0"))


@pytest.mark.parametrize(
    ("standard", "expected"),
    [
        (MinersInchStandard.COLORADO, Decimal("0.026")),
        (MinersInchStandard.ARIZONA, Decimal("0.025")),
        (MinersInchStandard.IDAHO, Decimal("0.020")),
    ],
)
def test_one_miners_inch_depends_on_the_statute(
    standard: MinersInchStandard, expected: Decimal
) -> None:
    assert miners_inches_to_cfs(Decimal("1"), standard) == expected


def test_miners_inches_round_trip_under_one_standard() -> None:
    cfs = miners_inches_to_cfs(Decimal("38.4"), MinersInchStandard.COLORADO)
    assert cfs == Decimal("1.000")
    assert cfs_to_miners_inches(cfs, MinersInchStandard.COLORADO) == Decimal("38.40")


def test_negative_miners_inches_are_refused() -> None:
    with pytest.raises(ValidationError, match="may not be negative"):
        miners_inches_to_cfs(Decimal("-1"), MinersInchStandard.UTAH)


def test_a_pump_rating_converts_from_gallons_per_minute() -> None:
    assert gpm_to_cfs(Decimal("449")) == Decimal("1.000")


def test_a_negative_pump_rate_is_refused() -> None:
    with pytest.raises(ValidationError, match="pump rate"):
        gpm_to_cfs(Decimal("-1"))


def test_applied_depth_is_reported_in_inches() -> None:
    assert depth_over_acres(Decimal("10"), Decimal("40")) == Decimal("3.00")


def test_applied_depth_needs_acres() -> None:
    with pytest.raises(ValidationError, match="no acres"):
        depth_over_acres(Decimal("10"), Decimal("0"))
