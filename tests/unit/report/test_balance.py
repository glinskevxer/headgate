from datetime import date, datetime, timedelta
from decimal import Decimal

import pytest

from headgate.errors import PolicyError
from headgate.ids import DeviceTag, TurnoutCode
from headgate.measure.delivery import DeliveryLedger, record_for
from headgate.measure.integrate import integrate
from headgate.model.device import Calibration, Device, DeviceKind
from headgate.model.reading import ReadingSeries, StaffReading
from headgate.report.balance import Balance, MonthBalance, build
from headgate.wateryear import Span

TURNOUT = TurnoutCode("L2-14")
CANAL = DeviceTag("FLUME-MAIN")
WEIR = DeviceTag("WEIR-L2-14")
CALIBRATION = Calibration(date(2025, 4, 1), "R. Aldrich", date(2026, 4, 1))


def span() -> Span:
    return Span(datetime(2025, 6, 1), datetime(2025, 8, 1))


def weir() -> Device:
    return Device(
        tag=WEIR,
        kind=DeviceKind.CIPOLLETTI_WEIR,
        installed=date(2016, 3, 1),
        crest_width_feet=Decimal("3"),
        turnout=TURNOUT,
        calibrations=(CALIBRATION,),
    )


def flume() -> Device:
    return Device(
        tag=CANAL,
        kind=DeviceKind.PARSHALL_FLUME,
        installed=date(2011, 5, 1),
        throat_width_feet=Decimal("4"),
        ditch=None,
        turnout=TurnoutCode("MAIN-3"),
        calibrations=(CALIBRATION,),
    )


def series(tag: DeviceTag, head: str) -> ReadingSeries:
    start = datetime(2025, 6, 1)
    return ReadingSeries(
        tag,
        tuple(
            StaffReading(
                device=tag,
                taken_at=start + timedelta(days=index * 7),
                observer="D. Yardley",
                head_feet=Decimal(head),
            )
            for index in range(9)
        ),
    )


def balance(turnout_head: str = "0.60", fraction: str = "0.1") -> Balance:
    headgate = integrate(flume(), series(CANAL, "1.20"), span())
    ledger = DeliveryLedger(
        span=span(),
        records=(record_for(TURNOUT, weir(), series(WEIR, turnout_head), span()),),
    )
    return build(2025, headgate, ledger, Decimal(fraction))


def test_the_season_is_cut_into_months() -> None:
    found = balance()
    assert [item.month for item in found.months] == [6, 7]
    assert found.headgate_af > found.delivered_af


def test_each_month_reports_its_carriage() -> None:
    found = balance()
    assert Decimal("0") < found.month(6).carriage < Decimal("1")


def test_a_month_losing_more_than_the_rates_allow_is_out_of_balance() -> None:
    found = balance(turnout_head="0.20")
    assert found.out_of_balance
    assert found.worst_month is not None


def test_a_month_inside_the_rates_is_in_balance() -> None:
    found = balance(turnout_head="0.60", fraction="0.8")
    assert found.out_of_balance == ()


def test_a_month_that_is_not_in_the_balance_is_refused() -> None:
    with pytest.raises(PolicyError, match="not in this balance"):
        balance().month(1)


def test_an_impossible_loss_share_is_refused() -> None:
    with pytest.raises(PolicyError, match="not a share of the headgate"):
        balance(fraction="1.5")


def test_a_month_with_no_water_is_in_balance() -> None:
    quiet = MonthBalance(
        month=9, headgate_af=Decimal("0"), delivered_af=Decimal("0"), expected_loss_af=Decimal("0")
    )
    assert quiet.carriage == Decimal("0")
    assert not quiet.is_out_of_balance


def test_the_rows_carry_a_column_for_every_number() -> None:
    assert len(balance().rows()[0]) == 7


def test_the_summary_names_the_worst_month() -> None:
    summary = dict(balance(turnout_head="0.20").summary())
    assert summary["water year"] == "2025"
    assert summary["worst month"] in {"6", "7"}


def test_an_empty_season_has_no_worst_month() -> None:
    assert Balance(water_year=2025, months=()).worst_month is None
