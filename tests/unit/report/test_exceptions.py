from datetime import date, datetime
from decimal import Decimal

import pytest

from headgate.errors import ValidationError
from headgate.ids import DeviceTag, TurnoutCode
from headgate.measure.delivery import DeliveryLedger, record_for
from headgate.model.device import Calibration, Device, DeviceKind
from headgate.model.reading import ReadingSeries, StaffReading
from headgate.report.exceptions import Urgency, build, calibrations_running_out
from headgate.wateryear import Span

NEAR = TurnoutCode("L2-14")
FAR = TurnoutCode("L2-20")
TODAY = date(2025, 6, 1)


def device(turnout: TurnoutCode, expires: date = date(2026, 4, 1), **overrides: object) -> Device:
    fields: dict[str, object] = {
        "tag": DeviceTag(f"WEIR-{turnout}"),
        "kind": DeviceKind.CIPOLLETTI_WEIR,
        "installed": date(2016, 3, 1),
        "crest_width_feet": Decimal("3"),
        "turnout": turnout,
        "calibrations": (Calibration(date(2025, 4, 1), "R. Aldrich", expires),),
    }
    fields.update(overrides)
    return Device(**fields)  # type: ignore[arg-type]


def span() -> Span:
    return Span(datetime(2025, 6, 1, 6), datetime(2025, 6, 11, 6))


def series(turnout: TurnoutCode, head: str, day: int = 1) -> ReadingSeries:
    tag = DeviceTag(f"WEIR-{turnout}")
    return ReadingSeries(
        tag,
        (
            StaffReading(
                device=tag,
                taken_at=datetime(2025, 6, day, 6),
                observer="D. Yardley",
                head_feet=Decimal(head),
            ),
        ),
    )


def ledger(far_head: str = "0.40", far_day: int = 1) -> DeliveryLedger:
    return DeliveryLedger(
        span=span(),
        records=(
            record_for(NEAR, device(NEAR), series(NEAR, "0.60"), span()),
            record_for(FAR, device(FAR), series(FAR, far_head, far_day), span()),
        ),
    )


def test_a_clean_week_prints_nothing() -> None:
    report = build(TODAY, ledger(), (device(NEAR), device(FAR)))
    assert report.is_quiet
    assert report.rows() == []


def test_a_turnout_read_past_its_rating_shows_as_estimated() -> None:
    report = build(TODAY, ledger(far_head="1.40"), (device(NEAR), device(FAR)))
    assert not report.is_quiet
    assert any("estimated" in item.detail for item in report.exceptions)


def test_a_turnout_nobody_read_until_late_shows_a_gap() -> None:
    report = build(TODAY, ledger(far_day=5), (device(NEAR), device(FAR)))
    assert any("unaccounted for" in item.detail for item in report.exceptions)


def test_a_void_record_is_wanted_now() -> None:
    pulled = device(FAR, removed=date(2025, 5, 1))
    book = DeliveryLedger(
        span=span(),
        records=(
            record_for(NEAR, device(NEAR), series(NEAR, "0.60"), span()),
            record_for(FAR, pulled, series(FAR, "0.40"), span()),
        ),
    )
    report = build(TODAY, book, (device(NEAR),))
    assert report.now
    assert report.now[0].urgency is Urgency.NOW
    assert "nothing was measured" in report.now[0].detail
    assert report.costing_water


def test_a_lapsed_calibration_is_wanted_now() -> None:
    lapsed = device(NEAR, expires=date(2025, 5, 1))
    found = calibrations_running_out((lapsed,), TODAY)
    assert found[0].urgency is Urgency.NOW
    assert "no calibration stands" in found[0].detail


def test_a_calibration_about_to_lapse_is_wanted_this_week() -> None:
    soon = device(NEAR, expires=date(2025, 6, 20))
    found = calibrations_running_out((soon,), TODAY)
    assert found[0].urgency is Urgency.THIS_WEEK
    assert not found[0].costs_water


def test_a_calibration_with_a_year_left_is_left_alone() -> None:
    assert calibrations_running_out((device(NEAR),), TODAY) == ()


def test_a_device_out_of_the_ditch_is_not_chased() -> None:
    pulled = device(NEAR, removed=date(2025, 5, 1), expires=date(2025, 5, 1))
    assert calibrations_running_out((pulled,), TODAY) == ()


def test_a_negative_lookahead_is_refused() -> None:
    with pytest.raises(ValidationError, match="run backwards"):
        calibrations_running_out((device(NEAR),), TODAY, lookahead_days=-1)


def test_the_worst_things_come_first() -> None:
    lapsed = device(NEAR, expires=date(2025, 5, 1))
    report = build(TODAY, ledger(far_head="1.40"), (lapsed, device(FAR)))
    ranks = [item.urgency.rank for item in report.exceptions]
    assert ranks == sorted(ranks)


def test_the_lookahead_can_be_widened() -> None:
    soon = device(NEAR, expires=date(2025, 8, 1))
    assert calibrations_running_out((soon,), TODAY) == ()
    assert calibrations_running_out((soon,), TODAY, lookahead_days=90)


def test_a_report_describes_its_lines() -> None:
    report = build(TODAY, ledger(far_head="1.40"), (device(NEAR), device(FAR)))
    assert "this week:" in report.exceptions[0].describe()
    assert len(report.rows()[0]) == 4
