from datetime import date
from decimal import Decimal

import pytest

from headgate.errors import ValidationError
from headgate.ids import DeviceTag, DitchCode, TurnoutCode
from headgate.model.device import Calibration, Device, DeviceKind


def calibration(
    performed: date, expires: date, offset: str = "0", who: str = "R. Aldrich"
) -> Calibration:
    return Calibration(
        performed=performed,
        performed_by=who,
        expires=expires,
        staff_offset_feet=Decimal(offset),
    )


def weir(**overrides: object) -> Device:
    fields: dict[str, object] = {
        "tag": DeviceTag("WEIR-L2-14"),
        "kind": DeviceKind.CIPOLLETTI_WEIR,
        "installed": date(2016, 3, 1),
        "crest_width_feet": Decimal("3"),
        "turnout": TurnoutCode("L2-14"),
        "calibrations": (calibration(date(2024, 4, 1), date(2025, 4, 1)),),
    }
    fields.update(overrides)
    return Device(**fields)  # type: ignore[arg-type]


def test_a_device_kind_knows_the_word_in_its_tag() -> None:
    assert DeviceKind.PARSHALL_FLUME.tag_word == "FLUME"
    assert DeviceKind.SUBMERGED_ORIFICE.tag_word == "ORIFICE"
    assert DeviceKind.PROPELLER_METER.tag_word == "METER"


def test_a_tag_that_disagrees_with_the_kind_is_refused() -> None:
    with pytest.raises(ValidationError, match="is tagged"):
        weir(tag=DeviceTag("FLUME-L2-14"))


def test_a_device_sits_at_exactly_one_place() -> None:
    with pytest.raises(ValidationError, match="not installed anywhere"):
        weir(turnout=None)
    with pytest.raises(ValidationError, match="cannot sit at a turnout and on a ditch"):
        weir(ditch=DitchCode("L2"))


def test_a_weir_needs_a_crest_width() -> None:
    with pytest.raises(ValidationError, match="no crest width"):
        weir(crest_width_feet=None)


def test_a_flume_does_not_need_a_crest_width() -> None:
    flume = Device(
        tag=DeviceTag("FLUME-MAIN"),
        kind=DeviceKind.PARSHALL_FLUME,
        installed=date(2011, 5, 1),
        throat_width_feet=Decimal("4"),
        ditch=DitchCode("MAIN"),
    )
    assert flume.site == "MAIN"


def test_an_empty_head_range_is_refused() -> None:
    with pytest.raises(ValidationError, match="empty head range"):
        weir(min_head_feet=Decimal("2"), max_head_feet=Decimal("1"))


def test_a_head_range_starting_at_zero_is_refused() -> None:
    with pytest.raises(ValidationError, match="at or below zero head"):
        weir(min_head_feet=Decimal("0"))


def test_a_negative_crest_width_is_refused() -> None:
    with pytest.raises(ValidationError, match="crest width of"):
        weir(crest_width_feet=Decimal("-1"))


def test_a_flume_needs_a_throat_width() -> None:
    with pytest.raises(ValidationError, match="no throat width"):
        Device(
            tag=DeviceTag("FLUME-MAIN"),
            kind=DeviceKind.CUTTHROAT_FLUME,
            installed=date(2011, 5, 1),
            ditch=DitchCode("MAIN"),
        )


def test_an_orifice_needs_an_opening_height() -> None:
    with pytest.raises(ValidationError, match="no opening height"):
        Device(
            tag=DeviceTag("ORIFICE-L2-14"),
            kind=DeviceKind.SUBMERGED_ORIFICE,
            installed=date(2011, 5, 1),
            throat_width_feet=Decimal("2"),
            turnout=TurnoutCode("L2-14"),
        )


def test_only_a_rectangular_weir_can_be_contracted() -> None:
    with pytest.raises(ValidationError, match="can be contracted"):
        weir(end_contractions=2)


def test_an_impossible_contraction_count_is_refused() -> None:
    with pytest.raises(ValidationError, match="claims 3 contractions"):
        weir(kind=DeviceKind.RECTANGULAR_WEIR, end_contractions=3)


def test_a_device_removed_before_installation_is_refused() -> None:
    with pytest.raises(ValidationError, match="removed before it was installed"):
        weir(removed=date(2015, 1, 1))


def test_calibrations_are_kept_in_the_order_they_were_done() -> None:
    with pytest.raises(ValidationError, match="out of order"):
        weir(
            calibrations=(
                calibration(date(2024, 4, 1), date(2025, 4, 1)),
                calibration(date(2023, 4, 1), date(2024, 4, 1)),
            )
        )


def test_a_calibration_must_expire_after_it_was_done() -> None:
    with pytest.raises(ValidationError, match="cannot expire"):
        calibration(date(2024, 4, 1), date(2024, 4, 1))


def test_a_calibration_says_who_did_it() -> None:
    with pytest.raises(ValidationError, match="who did it"):
        calibration(date(2024, 4, 1), date(2025, 4, 1), who=" ")


def test_a_large_staff_offset_means_the_gauge_was_reset() -> None:
    with pytest.raises(ValidationError, match="gauge was reset"):
        calibration(date(2024, 4, 1), date(2025, 4, 1), offset="0.75")


def test_a_device_is_in_service_between_its_dates() -> None:
    device = weir(removed=date(2025, 6, 1))
    assert not device.in_service_on(date(2016, 2, 28))
    assert device.in_service_on(date(2024, 7, 1))
    assert not device.in_service_on(date(2025, 6, 1))


def test_a_calibration_stands_until_it_expires() -> None:
    device = weir()
    assert device.is_calibrated_on(date(2024, 7, 1))
    assert not device.is_calibrated_on(date(2025, 4, 1))
    assert not device.is_calibrated_on(date(2024, 3, 31))


def test_the_latest_covering_calibration_is_the_one_that_counts() -> None:
    device = weir(
        calibrations=(
            calibration(date(2024, 4, 1), date(2025, 4, 1), "0.01"),
            calibration(date(2024, 8, 1), date(2025, 8, 1), "0.04"),
        )
    )
    assert device.staff_offset_on(date(2024, 9, 1)) == Decimal("0.04")
    assert device.staff_offset_on(date(2024, 5, 1)) == Decimal("0.01")


def test_an_uncalibrated_day_reads_with_no_offset() -> None:
    assert weir().staff_offset_on(date(2026, 1, 1)) == Decimal("0")


def test_a_head_outside_the_range_is_out_of_range() -> None:
    device = weir()
    assert device.head_in_range(Decimal("0.62"))
    assert not device.head_in_range(Decimal("0.01"))
    assert not device.head_in_range(Decimal("2.4"))


def test_adding_a_calibration_keeps_them_in_order() -> None:
    device = weir().with_calibration(calibration(date(2023, 4, 1), date(2024, 4, 1)))
    assert [item.performed.year for item in device.calibrations] == [2023, 2024]
