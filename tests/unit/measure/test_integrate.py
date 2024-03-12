from datetime import date, datetime
from decimal import Decimal

from headgate.ids import DeviceTag, TurnoutCode
from headgate.measure.integrate import Integration, integrate
from headgate.measure.quality import Provenance
from headgate.model.device import Calibration, Device, DeviceKind
from headgate.model.reading import ReadingSeries, StaffReading
from headgate.wateryear import Span

WEIR = DeviceTag("WEIR-L2-14")
CALIBRATION = Calibration(date(2024, 4, 1), "R. Aldrich", date(2025, 4, 1))


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


def reading(day: int, head: str, hour: int = 6) -> StaffReading:
    return StaffReading(
        device=WEIR,
        taken_at=datetime(2024, 6, day, hour),
        observer="D. Yardley",
        head_feet=Decimal(head),
    )


def span(first: int, last: int) -> Span:
    return Span(datetime(2024, 6, first, 6), datetime(2024, 6, last, 6))


def test_one_steady_reading_holds_for_the_whole_span() -> None:
    series = ReadingSeries(WEIR, (reading(1, "0.50"),))
    volume = integrate(device(), series, span(1, 3))
    assert volume.provenance is Provenance.MEASURED
    assert volume.total_af == Decimal("14.1660")


def test_the_step_rule_holds_each_reading_until_the_next() -> None:
    series = ReadingSeries(WEIR, (reading(1, "0.50"), reading(2, "1.00")))
    volume = integrate(device(), series, span(1, 3))
    assert len(volume.segments) == 2
    assert volume.segments[0].rate_cfs < volume.segments[1].rate_cfs


def test_the_trapezoid_rule_ramps_between_readings() -> None:
    series = ReadingSeries(WEIR, (reading(1, "0.50"), reading(2, "1.00")))
    stepped = integrate(device(), series, span(1, 3))
    ramped = integrate(device(), series, span(1, 3), Integration.TRAPEZOID)
    assert ramped.total_af > stepped.total_af


def test_a_span_that_opens_before_the_first_reading_is_partly_void() -> None:
    series = ReadingSeries(WEIR, (reading(2, "0.50"),))
    volume = integrate(device(), series, span(1, 3))
    assert volume.provenance is Provenance.VOID
    assert volume.unaccounted_seconds == Decimal("86400.0")
    assert volume.total_af > Decimal("0")


def test_a_device_nobody_read_delivers_nothing_anybody_can_account_for() -> None:
    volume = integrate(device(), ReadingSeries(WEIR), span(1, 3))
    assert volume.provenance is Provenance.VOID
    assert volume.total_af == Decimal("0")
    assert "nobody read the device" in volume.segments[0].reason


def test_a_lapsed_calibration_makes_the_whole_total_an_estimate() -> None:
    series = ReadingSeries(
        WEIR,
        (
            StaffReading(
                device=WEIR,
                taken_at=datetime(2025, 6, 1, 6),
                observer="D. Yardley",
                head_feet=Decimal("0.5"),
            ),
        ),
    )
    volume = integrate(device(), series, Span(datetime(2025, 6, 1, 6), datetime(2025, 6, 3, 6)))
    assert volume.provenance is Provenance.ESTIMATED
    assert volume.measured_af == Decimal("0")
    assert volume.estimated_af == volume.total_af


def test_measured_and_estimated_pieces_are_reported_apart() -> None:
    series = ReadingSeries(WEIR, (reading(1, "0.50"), reading(2, "1.40")))
    volume = integrate(device(), series, span(1, 3))
    assert volume.measured_af > Decimal("0")
    assert volume.estimated_af > Decimal("0")
    assert volume.measured_af + volume.estimated_af == volume.total_af


def test_the_mean_rate_is_the_volume_spread_over_the_span() -> None:
    series = ReadingSeries(WEIR, (reading(1, "0.50"),))
    volume = integrate(device(), series, span(1, 3))
    expected = volume.segments[0].rate_cfs
    assert abs(volume.mean_rate_cfs - expected) < Decimal("0.01")


def test_a_reading_taken_after_the_span_does_not_count() -> None:
    series = ReadingSeries(WEIR, (reading(1, "0.50"), reading(9, "1.00")))
    volume = integrate(device(), series, span(1, 3))
    assert len(volume.segments) == 1


def test_a_void_reading_leaves_its_segment_unaccounted() -> None:
    removed = device(removed=date(2024, 6, 2))
    series = ReadingSeries(WEIR, (reading(1, "0.50"), reading(2, "0.50")))
    volume = integrate(removed, series, span(1, 3))
    assert volume.provenance is Provenance.VOID
    assert volume.unaccounted_seconds == Decimal("86400.0")


def test_the_trapezoid_rule_falls_back_when_the_closing_reading_is_void() -> None:
    removed = device(removed=date(2024, 6, 2))
    series = ReadingSeries(WEIR, (reading(1, "0.50"), reading(2, "0.50")))
    volume = integrate(removed, series, span(1, 3), Integration.TRAPEZOID)
    assert volume.segments[0].provenance is Provenance.MEASURED
    assert volume.segments[1].provenance is Provenance.VOID


def test_the_trapezoid_rule_carries_the_weaker_of_the_two_ends() -> None:
    series = ReadingSeries(WEIR, (reading(1, "0.50"), reading(2, "1.40")))
    volume = integrate(device(), series, span(1, 3), Integration.TRAPEZOID)
    assert volume.provenance is Provenance.ESTIMATED
    assert "closing reading" in volume.segments[0].reason


def test_segments_cover_the_span_exactly() -> None:
    series = ReadingSeries(WEIR, (reading(1, "0.50"), reading(2, "0.80"), reading(3, "0.60")))
    volume = integrate(device(), series, span(1, 4))
    covered = sum((piece.span.seconds for piece in volume.segments), Decimal("0"))
    assert covered == span(1, 4).seconds
