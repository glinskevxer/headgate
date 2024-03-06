from datetime import date
from decimal import Decimal

import pytest

from headgate.errors import HeadOutOfRangeError, PolicyError
from headgate.ids import DeviceTag, DitchCode, TurnoutCode
from headgate.model.device import Calibration, Device, DeviceKind
from headgate.rating.flume import ParshallFlume
from headgate.rating.orifice import SubmergedOrifice
from headgate.rating.select import discharge_for, rated_range, rating_for
from headgate.rating.weir import ContractedRectangularWeir

CALIBRATION = Calibration(
    performed=date(2024, 4, 1),
    performed_by="R. Aldrich",
    expires=date(2025, 4, 1),
    staff_offset_feet=Decimal("0.02"),
)


def device(kind: DeviceKind, tag: str, **overrides: object) -> Device:
    fields: dict[str, object] = {
        "tag": DeviceTag(tag),
        "kind": kind,
        "installed": date(2016, 3, 1),
        "turnout": TurnoutCode("L2-14"),
        "calibrations": (CALIBRATION,),
    }
    fields.update(overrides)
    return Device(**fields)  # type: ignore[arg-type]


def test_a_cipolletti_device_gets_a_cipolletti_rating() -> None:
    weir = device(DeviceKind.CIPOLLETTI_WEIR, "WEIR-L2-14", crest_width_feet=Decimal("3"))
    assert "Cipolletti" in rating_for(weir, date(2024, 6, 1)).describe()


def test_the_calibration_that_stood_on_the_day_sets_the_offset() -> None:
    weir = device(DeviceKind.CIPOLLETTI_WEIR, "WEIR-L2-14", crest_width_feet=Decimal("3"))
    during = discharge_for(weir, date(2024, 6, 1), Decimal("0.5"))
    after = discharge_for(weir, date(2025, 6, 1), Decimal("0.5"))
    assert during > after


def test_a_contracted_weir_is_chosen_by_its_contraction_count() -> None:
    weir = device(
        DeviceKind.RECTANGULAR_WEIR,
        "WEIR-L2-14",
        crest_width_feet=Decimal("4"),
        end_contractions=2,
    )
    assert isinstance(rating_for(weir, date(2024, 6, 1)), ContractedRectangularWeir)


def test_a_plain_rectangular_weir_is_rated_suppressed() -> None:
    weir = device(DeviceKind.RECTANGULAR_WEIR, "WEIR-L2-14", crest_width_feet=Decimal("4"))
    assert "suppressed" in rating_for(weir, date(2024, 6, 1)).describe()


def test_a_v_notch_needs_no_dimensions() -> None:
    notch = device(DeviceKind.V_NOTCH_WEIR, "WEIR-L2-14")
    assert "V notch" in rating_for(notch, date(2024, 6, 1)).describe()


def test_flumes_are_rated_off_their_throat() -> None:
    flume = device(DeviceKind.PARSHALL_FLUME, "FLUME-L2-14", throat_width_feet=Decimal("2"))
    curve = rating_for(flume, date(2024, 6, 1))
    assert isinstance(curve, ParshallFlume)
    assert curve.throat_width_feet == Decimal("2")


def test_a_cutthroat_is_picked_by_kind_not_by_tag() -> None:
    flume = device(DeviceKind.CUTTHROAT_FLUME, "FLUME-L2-14", throat_width_feet=Decimal("1.5"))
    assert "cutthroat" in rating_for(flume, date(2024, 6, 1)).describe()


def test_an_orifice_is_rated_off_both_of_its_dimensions() -> None:
    gate = device(
        DeviceKind.SUBMERGED_ORIFICE,
        "ORIFICE-L2-14",
        throat_width_feet=Decimal("2"),
        opening_height_feet=Decimal("1"),
    )
    curve = rating_for(gate, date(2024, 6, 1))
    assert isinstance(curve, SubmergedOrifice)
    assert curve.area_sqft == Decimal("2")


def test_a_meter_has_no_rating_because_it_totalises() -> None:
    meter = device(DeviceKind.PROPELLER_METER, "METER-L2-14")
    with pytest.raises(PolicyError, match="totalises"):
        rating_for(meter, date(2024, 6, 1))


def test_a_device_out_of_the_ditch_has_no_rating() -> None:
    weir = device(
        DeviceKind.CIPOLLETTI_WEIR,
        "WEIR-L2-14",
        crest_width_feet=Decimal("3"),
        removed=date(2024, 5, 1),
    )
    with pytest.raises(PolicyError, match="not in the ditch"):
        rating_for(weir, date(2024, 6, 1))


def test_a_reading_past_the_rated_range_still_says_so() -> None:
    weir = device(DeviceKind.CIPOLLETTI_WEIR, "WEIR-L2-14", crest_width_feet=Decimal("3"))
    with pytest.raises(HeadOutOfRangeError):
        discharge_for(weir, date(2024, 6, 1), Decimal("1.4"))


def test_the_rated_range_comes_from_the_structure() -> None:
    weir = device(DeviceKind.CIPOLLETTI_WEIR, "WEIR-L2-14", crest_width_feet=Decimal("6"))
    low, high = rated_range(weir, date(2024, 6, 1))
    assert low == Decimal("0.2")
    assert high == Decimal("2.000")


def test_a_flume_on_a_ditch_rather_than_a_turnout_still_rates() -> None:
    flume = device(
        DeviceKind.PARSHALL_FLUME,
        "FLUME-MAIN",
        throat_width_feet=Decimal("4"),
        turnout=None,
        ditch=DitchCode("MAIN"),
    )
    assert discharge_for(flume, date(2024, 6, 1), Decimal("1")) > Decimal("0")
