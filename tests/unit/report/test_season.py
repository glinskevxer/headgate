from datetime import date, datetime
from decimal import Decimal

import pytest

from headgate.carriage.apportion import LossPolicy, apportion
from headgate.errors import PolicyError
from headgate.ids import DeviceTag, DitchCode, TurnoutCode
from headgate.measure.delivery import DeliveryLedger, record_for
from headgate.model.device import Calibration, Device, DeviceKind
from headgate.model.ditch import Ditch, DitchSystem, Turnout
from headgate.model.reading import ReadingSeries, StaffReading
from headgate.report.season import build
from headgate.wateryear import Span

NEAR = TurnoutCode("MAIN-3")
FAR = TurnoutCode("L2-14")
CALIBRATION = Calibration(date(2024, 4, 1), "R. Aldrich", date(2025, 4, 1))


def system() -> DitchSystem:
    main = Ditch(
        code=DitchCode("MAIN"),
        name="Sanpete Main Canal",
        capacity_cfs=Decimal("48"),
        length_feet=Decimal("26400"),
        loss_fraction_per_mile=Decimal("0.02"),
        turnouts=(Turnout(NEAR, "Bench gate", Decimal("5280"), Decimal("6"), Decimal("40")),),
        diversion_mile=Decimal("28.4"),
    )
    lateral = Ditch(
        code=DitchCode("L2"),
        name="Second Lateral",
        capacity_cfs=Decimal("12"),
        length_feet=Decimal("10560"),
        loss_fraction_per_mile=Decimal("0.05"),
        turnouts=(Turnout(FAR, "Lower gate", Decimal("5280"), Decimal("6"), Decimal("40")),),
        parent=DitchCode("MAIN"),
        offtake_station_feet=Decimal("15840"),
    )
    return DitchSystem(ditches=(main, lateral))


def span() -> Span:
    return Span(datetime(2024, 6, 1, 6), datetime(2024, 6, 11, 6))


def device(turnout: TurnoutCode, **overrides: object) -> Device:
    fields: dict[str, object] = {
        "tag": DeviceTag(f"WEIR-{turnout}"),
        "kind": DeviceKind.CIPOLLETTI_WEIR,
        "installed": date(2016, 3, 1),
        "crest_width_feet": Decimal("3"),
        "turnout": turnout,
        "calibrations": (CALIBRATION,),
    }
    fields.update(overrides)
    return Device(**fields)  # type: ignore[arg-type]


def series(turnout: TurnoutCode, head: str, when: datetime | None = None) -> ReadingSeries:
    tag = DeviceTag(f"WEIR-{turnout}")
    return ReadingSeries(
        tag,
        (
            StaffReading(
                device=tag,
                taken_at=when or datetime(2024, 6, 1, 6),
                observer="D. Yardley",
                head_feet=Decimal(head),
            ),
        ),
    )


def ledger(far_head: str = "0.40") -> DeliveryLedger:
    return DeliveryLedger(
        span=span(),
        records=(
            record_for(NEAR, device(NEAR), series(NEAR, "0.60"), span()),
            record_for(FAR, device(FAR), series(FAR, far_head), span()),
        ),
    )


def report(headgate: str = "180", far_head: str = "0.40"):  # type: ignore[no-untyped-def]
    book = ledger(far_head)
    split = apportion(
        book.volumes(),
        Decimal(headgate) - book.total_af,
        LossPolicy.BY_LEG,
        system=system(),
    )
    return build(2024, "Sanpete Ditch Company", book, split, Decimal(headgate), system())


def test_the_report_totals_what_was_delivered() -> None:
    built = report()
    assert built.delivered_af == ledger().total_af
    assert built.headgate_af == Decimal("180")


def test_the_loss_is_the_headgate_less_the_turnouts() -> None:
    built = report()
    assert built.loss_af == built.headgate_af - built.delivered_af


def test_a_leaking_ditch_shows_unexplained_loss() -> None:
    tight = report("150")
    leaking = report("300")
    assert leaking.unexplained_loss_af > tight.unexplained_loss_af


def test_carriage_efficiency_is_reported_as_a_fraction() -> None:
    built = report()
    assert Decimal("0") < built.carriage_efficiency < Decimal("1")


def test_a_clean_season_is_proved_all_through() -> None:
    built = report()
    assert built.proved_share == Decimal("1.000")
    assert built.unproved_turnouts == ()


def test_a_reading_past_the_rating_shows_as_unproved() -> None:
    built = report(headgate="330", far_head="1.40")
    assert built.proved_share < Decimal("1.000")
    assert FAR in built.unproved_turnouts


def test_each_turnout_gets_a_line_with_its_charged_loss() -> None:
    built = report()
    line = built.line_for(FAR)
    assert line.loss_af > Decimal("0")
    assert line.charged_af == line.delivered_af + line.loss_af


def test_the_far_turnout_carries_more_loss_than_the_near_one() -> None:
    built = report()
    assert built.line_for(FAR).loss_af > built.line_for(NEAR).loss_af


def test_asking_for_a_turnout_that_did_not_run_is_refused() -> None:
    with pytest.raises(PolicyError, match="not on the 2024 report"):
        report().line_for(TurnoutCode("L2-99"))


def test_the_rows_come_out_one_a_turnout() -> None:
    rows = report().rows()
    assert len(rows) == 2
    assert rows[0][0] == str(FAR)


def test_the_summary_names_the_district_and_the_year() -> None:
    summary = dict(report().summary())
    assert summary["district"] == "Sanpete Ditch Company"
    assert summary["water year"] == "2024"
    assert "acre feet" in summary["headgate"]


def test_a_turnout_charged_no_loss_is_refused() -> None:
    book = ledger()
    split = apportion({NEAR: book.for_turnout(NEAR).total_af}, Decimal("5"), LossPolicy.BY_DELIVERY)
    with pytest.raises(PolicyError, match="charged no loss"):
        build(2024, "Sanpete", book, split, Decimal("180"), system())


def test_turnouts_that_took_more_than_the_headgate_passed_are_refused() -> None:
    book = ledger()
    split = apportion(book.volumes(), Decimal("1"), LossPolicy.BY_DELIVERY)
    with pytest.raises(PolicyError, match="not possible"):
        build(2024, "Sanpete", book, split, Decimal("1"), system())
