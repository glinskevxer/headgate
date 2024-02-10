from datetime import date
from decimal import Decimal

import pytest

from headgate.errors import NotFoundError, PolicyError, ValidationError
from headgate.ids import AccountNumber, TurnoutCode
from headgate.model.parcel import CropCode, Parcel, PlaceOfUse


def parcel(
    parcel_id: str,
    account: int,
    turnout: str,
    acres: str,
    crop: CropCode = CropCode.ALFALFA,
    dried: date | None = None,
) -> Parcel:
    return Parcel(
        parcel_id=parcel_id,
        account=AccountNumber(account),
        turnout=TurnoutCode(turnout),
        irrigated_acres=Decimal(acres),
        crop=crop,
        dried_up_on=dried,
    )


def place() -> PlaceOfUse:
    return PlaceOfUse(
        parcels=(
            parcel("11-042-001", 118, "L2-14", "40"),
            parcel("11-042-002", 118, "L2-20", "22.5", CropCode.PASTURE),
            parcel("11-043-014", 212, "L2-20", "60", CropCode.SMALL_GRAIN),
        ),
        decreed_acres=Decimal("120"),
    )


def test_a_parcel_number_has_the_assessor_shape() -> None:
    with pytest.raises(ValidationError, match="not a parcel number"):
        parcel("11042001", 118, "L2-14", "40")


def test_a_parcel_needs_acres() -> None:
    with pytest.raises(ValidationError, match="no irrigated acres"):
        parcel("11-042-001", 118, "L2-14", "0")


def test_a_fallow_parcel_must_say_when_it_went_out() -> None:
    with pytest.raises(ValidationError, match="out of production"):
        parcel("11-042-001", 118, "L2-14", "40", CropCode.FALLOW)


def test_fallow_is_the_only_crop_that_is_not_irrigated() -> None:
    assert CropCode.ALFALFA.is_irrigated
    assert not CropCode.FALLOW.is_irrigated


def test_a_dried_parcel_carries_no_acres_after_the_date() -> None:
    dry = parcel("11-042-001", 118, "L2-14", "40", CropCode.FALLOW, date(2024, 6, 1))
    assert dry.acres_on(date(2024, 5, 31)) == Decimal("40")
    assert dry.acres_on(date(2024, 6, 1)) == Decimal("0")


def test_a_place_of_use_refuses_a_repeated_parcel() -> None:
    with pytest.raises(ValidationError, match="listed twice"):
        PlaceOfUse(parcels=(parcel("11-042-001", 118, "L2-14", "40"),) * 2)


def test_a_place_of_use_refuses_an_empty_decree() -> None:
    with pytest.raises(ValidationError, match="not a place of use"):
        PlaceOfUse(parcels=(), decreed_acres=Decimal("0"))


def test_acres_add_up_across_the_whole_place() -> None:
    assert place().acres_on(date(2024, 6, 1)) == Decimal("122.5")


def test_acres_add_up_by_turnout_and_by_account() -> None:
    served = place()
    assert served.acres_under(TurnoutCode("L2-20"), date(2024, 6, 1)) == Decimal("82.5")
    assert served.acres_of(AccountNumber(118), date(2024, 6, 1)) == Decimal("62.5")


def test_the_turnouts_in_production_come_back_sorted() -> None:
    assert place().turnouts(date(2024, 6, 1)) == (TurnoutCode("L2-14"), TurnoutCode("L2-20"))


def test_acreage_over_the_decree_is_reported() -> None:
    assert place().over_decree_on(date(2024, 6, 1)) == Decimal("2.5")


def test_a_place_within_its_decree_reports_nothing_over() -> None:
    within = PlaceOfUse(parcels=place().parcels, decreed_acres=Decimal("200"))
    assert within.over_decree_on(date(2024, 6, 1)) == Decimal("0")


def test_a_place_with_no_decreed_acreage_is_never_over() -> None:
    loose = PlaceOfUse(parcels=place().parcels)
    assert loose.over_decree_on(date(2024, 6, 1)) == Decimal("0")


def test_drying_up_a_parcel_takes_its_acres_out() -> None:
    after = place().dry_up("11-042-001", date(2024, 7, 1))
    assert after.acres_on(date(2024, 7, 1)) == Decimal("82.5")
    assert after.acres_on(date(2024, 6, 30)) == Decimal("122.5")
    assert after.parcel("11-042-001").crop is CropCode.FALLOW


def test_drying_up_the_same_parcel_twice_is_refused() -> None:
    after = place().dry_up("11-042-001", date(2024, 7, 1))
    with pytest.raises(PolicyError, match="already dry"):
        after.dry_up("11-042-001", date(2024, 8, 1))


def test_an_unknown_parcel_is_reported_missing() -> None:
    with pytest.raises(NotFoundError, match="no parcel"):
        place().parcel("99-999-999")
