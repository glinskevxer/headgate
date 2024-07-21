from datetime import date, datetime
from decimal import Decimal

import pytest

from headgate.errors import PolicyError, ValidationError
from headgate.ids import DeviceTag, TurnoutCode
from headgate.measure.delivery import DeliveryLedger, DeliveryRecord, record_for
from headgate.measure.quality import Provenance
from headgate.model.device import Calibration, Device, DeviceKind
from headgate.model.reading import ReadingSeries, StaffReading
from headgate.wateryear import Span

TURNOUT = TurnoutCode("L2-14")
OTHER = TurnoutCode("L2-20")
WEIR = DeviceTag("WEIR-L2-14")
CALIBRATION = Calibration(date(2024, 4, 1), "R. Aldrich", date(2025, 4, 1))


def device(tag: DeviceTag = WEIR, turnout: TurnoutCode = TURNOUT, **overrides: object) -> Device:
    fields: dict[str, object] = {
        "tag": tag,
        "kind": DeviceKind.CIPOLLETTI_WEIR,
        "installed": date(2016, 3, 1),
        "crest_width_feet": Decimal("3"),
        "turnout": turnout,
        "calibrations": (CALIBRATION,),
    }
    fields.update(overrides)
    return Device(**fields)  # type: ignore[arg-type]


def series(tag: DeviceTag = WEIR, head: str = "0.50") -> ReadingSeries:
    return ReadingSeries(
        tag,
        (
            StaffReading(
                device=tag,
                taken_at=datetime(2024, 6, 1, 6),
                observer="D. Yardley",
                head_feet=Decimal(head),
            ),
        ),
    )


def span() -> Span:
    return Span(datetime(2024, 6, 1, 6), datetime(2024, 6, 4, 6))


def test_a_record_carries_the_volume_and_where_it_came_from() -> None:
    record = record_for(TURNOUT, device(), series(), span())
    assert record.total_af > Decimal("0")
    assert record.is_proved
    assert record.device == WEIR
    assert record.span == span()


def test_a_record_reports_the_hours_nobody_accounted_for() -> None:
    late = ReadingSeries(
        WEIR,
        (
            StaffReading(
                device=WEIR,
                taken_at=datetime(2024, 6, 2, 6),
                observer="D. Yardley",
                head_feet=Decimal("0.5"),
            ),
        ),
    )
    record = record_for(TURNOUT, device(), late, span())
    assert record.unaccounted_hours == Decimal("24.00")
    assert not record.is_proved


def test_a_device_from_another_turnout_is_refused() -> None:
    with pytest.raises(PolicyError, match="measures"):
        record_for(OTHER, device(), series(), span())


def test_a_series_for_another_device_is_refused() -> None:
    with pytest.raises(PolicyError, match="is not for device"):
        record_for(TURNOUT, device(), series(DeviceTag("WEIR-L2-20")), span())


def test_a_lapsed_calibration_leaves_the_record_unproved() -> None:
    stale = ReadingSeries(
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
    record = record_for(
        TURNOUT, device(), stale, Span(datetime(2025, 6, 1, 6), datetime(2025, 6, 4, 6))
    )
    assert record.provenance is Provenance.ESTIMATED
    assert record.estimated_af == record.total_af


def ledger() -> DeliveryLedger:
    first = record_for(TURNOUT, device(), series(), span())
    second = record_for(
        OTHER,
        device(DeviceTag("WEIR-L2-20"), OTHER),
        series(DeviceTag("WEIR-L2-20"), "0.30"),
        span(),
    )
    return DeliveryLedger(span=span(), records=(first, second))


def test_a_ledger_totals_its_records() -> None:
    book = ledger()
    assert book.total_af == book.for_turnout(TURNOUT).total_af + book.for_turnout(OTHER).total_af


def test_a_ledger_lists_its_turnouts_sorted() -> None:
    assert ledger().turnouts == (TURNOUT, OTHER)


def test_a_clean_ledger_is_measured_all_through() -> None:
    book = ledger()
    assert book.provenance is Provenance.MEASURED
    assert book.estimated_af == Decimal("0")
    assert book.estimated_share == Decimal("0")
    assert book.unproved == ()


def test_one_bad_turnout_pulls_the_whole_ledger_down() -> None:
    good = record_for(TURNOUT, device(), series(), span())
    stale = record_for(
        OTHER,
        device(DeviceTag("WEIR-L2-20"), OTHER, removed=date(2024, 5, 1)),
        series(DeviceTag("WEIR-L2-20")),
        span(),
    )
    book = DeliveryLedger(span=span(), records=(good, stale))
    assert book.provenance is Provenance.VOID
    assert len(book.unproved) == 1


def test_the_estimated_share_is_reported_as_a_fraction() -> None:
    good = record_for(TURNOUT, device(), series(), span())
    weak = record_for(
        OTHER,
        device(DeviceTag("WEIR-L2-20"), OTHER),
        ReadingSeries(
            DeviceTag("WEIR-L2-20"),
            (
                StaffReading(
                    device=DeviceTag("WEIR-L2-20"),
                    taken_at=datetime(2024, 6, 1, 6),
                    observer="D. Yardley",
                    head_feet=Decimal("1.4"),
                ),
            ),
        ),
        span(),
    )
    book = DeliveryLedger(span=span(), records=(good, weak))
    assert book.estimated_share > Decimal("0")
    assert book.estimated_share < Decimal("1")


def test_an_empty_ledger_reports_no_estimate() -> None:
    book = DeliveryLedger(span=span(), records=())
    assert book.total_af == Decimal("0")
    assert book.estimated_share == Decimal("0")


def test_a_turnout_twice_in_one_ledger_is_refused() -> None:
    record = record_for(TURNOUT, device(), series(), span())
    with pytest.raises(ValidationError, match="appears twice"):
        DeliveryLedger(span=span(), records=(record, record))


def test_a_record_from_another_span_is_refused() -> None:
    other_span = Span(datetime(2024, 7, 1, 6), datetime(2024, 7, 4, 6))
    record = record_for(TURNOUT, device(), series(), span())
    with pytest.raises(ValidationError, match="different span"):
        DeliveryLedger(span=other_span, records=(record,))


def test_asking_for_a_turnout_that_did_not_run_is_refused() -> None:
    with pytest.raises(PolicyError, match="no record in this ledger"):
        ledger().for_turnout(TurnoutCode("L2-99"))


def test_the_volumes_come_out_in_the_shape_the_loss_split_wants() -> None:
    volumes = ledger().volumes()
    assert set(volumes) == {TURNOUT, OTHER}
    assert isinstance(volumes[TURNOUT], Decimal)


def test_a_record_can_be_built_by_hand_for_a_report() -> None:
    record = record_for(TURNOUT, device(), series(), span())
    rebuilt = DeliveryRecord(turnout=TURNOUT, device=WEIR, volume=record.volume)
    assert rebuilt.total_af == record.total_af
