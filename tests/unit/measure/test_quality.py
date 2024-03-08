from datetime import date, datetime
from decimal import Decimal

import pytest

from headgate.errors import PolicyError
from headgate.ids import DeviceTag, TurnoutCode
from headgate.measure.quality import (
    Provenance,
    is_totaliser,
    rate_reading,
    worst_of,
)
from headgate.model.device import Calibration, Device, DeviceKind
from headgate.model.reading import ReadingMethod, StaffReading

WEIR = DeviceTag("WEIR-L2-14")
CALIBRATION = Calibration(
    performed=date(2024, 4, 1),
    performed_by="R. Aldrich",
    expires=date(2025, 4, 1),
)


def device(**overrides: object) -> Device:
    fields: dict[str, object] = {
        "tag": WEIR,
        "kind": DeviceKind.CIPOLLETTI_WEIR,
        "installed": date(2016, 3, 1),
        "crest_width_feet": Decimal("3"),
        "turnout": TurnoutCode("L2-14"),
        "calibrations": (CALIBRATION,),
    }
    fields.update(overrides)
    return Device(**fields)  # type: ignore[arg-type]


def reading(head: str = "0.62", when: datetime | None = None, **overrides: object) -> StaffReading:
    fields: dict[str, object] = {
        "device": WEIR,
        "taken_at": when or datetime(2024, 6, 1, 7),
        "observer": "D. Yardley",
        "head_feet": Decimal(head),
    }
    fields.update(overrides)
    return StaffReading(**fields)  # type: ignore[arg-type]


def test_a_calibrated_device_in_range_is_measured() -> None:
    rated = rate_reading(device(), reading())
    assert rated.provenance is Provenance.MEASURED
    assert rated.rate > Decimal("0")
    assert "calibrated device in range" in rated.reason


def test_a_lapsed_calibration_leaves_an_estimate() -> None:
    rated = rate_reading(device(), reading(when=datetime(2025, 6, 1, 7)))
    assert rated.provenance is Provenance.ESTIMATED
    assert rated.rate > Decimal("0")
    assert "calibration had lapsed" in rated.reason


def test_a_reading_past_the_rating_is_estimated_at_the_end_of_the_curve() -> None:
    rated = rate_reading(device(), reading("1.4"))
    assert rated.provenance is Provenance.ESTIMATED
    assert rated.rate == rate_reading(device(), reading("1.0")).rate
    assert "good from" in rated.reason


def test_an_eyeballed_reading_is_estimated_however_good_the_device_is() -> None:
    rated = rate_reading(device(), reading(method=ReadingMethod.VISUAL))
    assert rated.provenance is Provenance.ESTIMATED
    assert "eyeballed" in rated.reason


def test_two_weaknesses_are_both_reported() -> None:
    rated = rate_reading(device(), reading("1.4", when=datetime(2025, 6, 1, 7)))
    assert "calibration had lapsed" in rated.reason
    assert "good from" in rated.reason


def test_a_device_out_of_the_ditch_voids_the_reading() -> None:
    rated = rate_reading(device(removed=date(2024, 5, 1)), reading())
    assert rated.provenance is Provenance.VOID
    assert rated.rate_cfs is None
    assert "not in the ditch" in rated.reason


def test_a_drowned_flume_is_void_not_estimated() -> None:
    flume = Device(
        tag=DeviceTag("FLUME-L2-14"),
        kind=DeviceKind.PARSHALL_FLUME,
        installed=date(2016, 3, 1),
        throat_width_feet=Decimal("1"),
        turnout=TurnoutCode("L2-14"),
    )
    drowned = StaffReading(
        device=DeviceTag("FLUME-L2-14"),
        taken_at=datetime(2024, 6, 1, 7),
        observer="D. Yardley",
        head_feet=Decimal("0.8"),
        tail_feet=Decimal("0.7"),
    )
    rated = rate_reading(flume, drowned)
    assert rated.provenance is Provenance.VOID
    assert "submerged" in rated.reason


def test_a_flume_below_its_submergence_limit_still_measures() -> None:
    flume = Device(
        tag=DeviceTag("FLUME-L2-14"),
        kind=DeviceKind.PARSHALL_FLUME,
        installed=date(2016, 3, 1),
        throat_width_feet=Decimal("3"),
        turnout=TurnoutCode("L2-14"),
        calibrations=(Calibration(date(2024, 4, 1), "R. Aldrich", date(2025, 4, 1)),),
    )
    fine = StaffReading(
        device=DeviceTag("FLUME-L2-14"),
        taken_at=datetime(2024, 6, 1, 7),
        observer="D. Yardley",
        head_feet=Decimal("1.0"),
        tail_feet=Decimal("0.6"),
    )
    assert rate_reading(flume, fine).provenance is Provenance.MEASURED


def test_a_meter_total_is_not_a_rate() -> None:
    meter = Device(
        tag=DeviceTag("METER-L2-14"),
        kind=DeviceKind.PROPELLER_METER,
        installed=date(2016, 3, 1),
        turnout=TurnoutCode("L2-14"),
    )
    total = StaffReading(
        device=DeviceTag("METER-L2-14"),
        taken_at=datetime(2024, 6, 1, 7),
        observer="D. Yardley",
        method=ReadingMethod.METER_TOTAL,
        meter_total_af=Decimal("14.2"),
    )
    rated = rate_reading(meter, total)
    assert rated.provenance is Provenance.VOID
    assert is_totaliser(meter)


def test_rating_a_reading_against_the_wrong_device_is_refused() -> None:
    with pytest.raises(PolicyError, match="rated against device"):
        rate_reading(device(), reading(device=DeviceTag("WEIR-L2-20")))


def test_only_a_measured_record_is_evidence() -> None:
    assert Provenance.MEASURED.counts_as_evidence
    assert not Provenance.ESTIMATED.counts_as_evidence
    assert Provenance.ESTIMATED.has_a_rate
    assert not Provenance.VOID.has_a_rate


def test_a_total_inherits_the_weakest_piece_that_went_into_it() -> None:
    assert worst_of([Provenance.MEASURED, Provenance.MEASURED]) is Provenance.MEASURED
    assert worst_of([Provenance.MEASURED, Provenance.ESTIMATED]) is Provenance.ESTIMATED
    assert worst_of([Provenance.ESTIMATED, Provenance.VOID]) is Provenance.VOID
    assert worst_of([]) is Provenance.VOID


def test_a_void_reading_reports_no_rate_but_answers_zero() -> None:
    rated = rate_reading(device(removed=date(2024, 5, 1)), reading())
    assert rated.rate_cfs is None
    assert rated.rate == Decimal("0")
