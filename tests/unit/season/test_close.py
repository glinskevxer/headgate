from datetime import date, datetime
from decimal import Decimal

import pytest

from headgate.assessment.tiers import Band, RateSchedule
from headgate.carriage.apportion import LossPolicy
from headgate.errors import PolicyError
from headgate.ids import AccountNumber, DeviceTag, DitchCode, TurnoutCode
from headgate.measure.delivery import DeliveryLedger, record_for
from headgate.model.device import Calibration, Device, DeviceKind
from headgate.model.ditch import Ditch, DitchSystem, Turnout
from headgate.model.reading import ReadingSeries, StaffReading
from headgate.money import Money
from headgate.season.close import close_season
from headgate.wateryear import Span

NEAR = TurnoutCode("MAIN-3")
FAR = TurnoutCode("L2-14")
HOLDER = AccountNumber(118)
OTHER = AccountNumber(212)
ISSUED = date(2024, 11, 1)
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


def device(turnout: TurnoutCode) -> Device:
    return Device(
        tag=DeviceTag(f"WEIR-{turnout}"),
        kind=DeviceKind.CIPOLLETTI_WEIR,
        installed=date(2016, 3, 1),
        crest_width_feet=Decimal("3"),
        turnout=turnout,
        calibrations=(CALIBRATION,),
    )


def series(turnout: TurnoutCode, head: str) -> ReadingSeries:
    tag = DeviceTag(f"WEIR-{turnout}")
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


def ledger() -> DeliveryLedger:
    return DeliveryLedger(
        span=span(),
        records=(
            record_for(NEAR, device(NEAR), series(NEAR, "0.60"), span()),
            record_for(FAR, device(FAR), series(FAR, "0.40"), span()),
        ),
    )


def schedule() -> RateSchedule:
    return RateSchedule(
        water_year=2024,
        per_share=Money.from_dollars("4.50"),
        bands=(
            Band(Decimal("50"), Money.from_dollars("2.00")),
            Band(None, Money.from_dollars("3.50")),
        ),
    )


def close(**overrides: object):  # type: ignore[no-untyped-def]
    arguments: dict[str, object] = {
        "water_year": 2024,
        "district": "Sanpete Ditch Company",
        "ledger": ledger(),
        "headgate_af": Decimal("180"),
        "system": system(),
        "schedule": schedule(),
        "turnout_accounts": {NEAR: HOLDER, FAR: OTHER},
        "shares": {HOLDER: Decimal("20"), OTHER: Decimal("12")},
        "issued_on": ISSUED,
    }
    arguments.update(overrides)
    return close_season(**arguments)  # type: ignore[arg-type]


def test_closing_a_season_bills_every_account() -> None:
    closed = close()
    assert closed.bills.accounts == (HOLDER, OTHER)
    assert closed.billed.cents > 0


def test_the_report_and_the_bills_come_off_the_same_ledger() -> None:
    closed = close()
    billed_water = sum((item.delivered_af for item in closed.accounts), Decimal("0"))
    assert billed_water == closed.report.delivered_af


def test_each_account_carries_its_turnouts_loss() -> None:
    closed = close()
    assert closed.account_season(OTHER).loss_af > Decimal("0")
    assert closed.account_season(OTHER).charged_af > closed.account_season(OTHER).delivered_af


def test_the_far_turnout_costs_its_owner_more_loss() -> None:
    closed = close()
    assert closed.account_season(OTHER).loss_af > closed.account_season(HOLDER).loss_af


def test_an_account_that_took_no_water_is_still_billed_for_its_shares() -> None:
    quiet = AccountNumber(300)
    closed = close(shares={HOLDER: Decimal("20"), OTHER: Decimal("12"), quiet: Decimal("4")})
    bill = closed.bill_for(quiet)
    assert bill.total == Money.from_dollars("18.00")
    assert closed.account_season(quiet).delivered_af == Decimal("0")


def test_a_turnout_with_no_owner_stops_the_close() -> None:
    with pytest.raises(PolicyError, match="no account stands behind it"):
        close(turnout_accounts={NEAR: HOLDER})


def test_a_season_where_nothing_ran_cannot_be_closed() -> None:
    with pytest.raises(PolicyError, match="nothing to close"):
        close(ledger=DeliveryLedger(span=span(), records=()))


def test_a_headgate_smaller_than_the_deliveries_stops_the_close() -> None:
    with pytest.raises(PolicyError, match="not possible"):
        close(headgate_af=Decimal("10"))


def test_charging_the_loss_by_delivery_moves_it_between_accounts() -> None:
    by_leg = close().account_season(OTHER).loss_af
    by_delivery = close(policy=LossPolicy.BY_DELIVERY).account_season(OTHER).loss_af
    assert by_leg != by_delivery


def test_charging_the_loss_by_share_needs_the_shares_at_each_turnout() -> None:
    with pytest.raises(PolicyError, match="needs the shares"):
        close(policy=LossPolicy.BY_SHARE)


def test_charging_by_share_works_when_the_shares_are_given() -> None:
    closed = close(
        policy=LossPolicy.BY_SHARE,
        turnout_shares={NEAR: Decimal("20"), FAR: Decimal("12")},
    )
    assert closed.account_season(HOLDER).loss_af > closed.account_season(OTHER).loss_af


def test_asking_about_an_account_that_was_not_in_the_season_is_refused() -> None:
    with pytest.raises(PolicyError, match="took no water"):
        close().account_season(AccountNumber(999))
