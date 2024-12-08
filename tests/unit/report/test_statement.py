from datetime import date, datetime
from decimal import Decimal

import pytest

from headgate.assessment.billing import bill_account
from headgate.assessment.payment import AccountLedger, Payment
from headgate.assessment.tiers import Band, RateSchedule
from headgate.errors import PolicyError
from headgate.ids import AccountNumber, DeviceTag, TurnoutCode
from headgate.measure.delivery import DeliveryLedger, record_for
from headgate.model.device import Calibration, Device, DeviceKind
from headgate.model.reading import ReadingSeries, StaffReading
from headgate.money import Money
from headgate.report.statement import Statement, build
from headgate.wateryear import Span

HOLDER = AccountNumber(118)
NEAR = TurnoutCode("L2-14")
FAR = TurnoutCode("L2-20")
DUE = date(2025, 12, 1)
CALIBRATION = Calibration(date(2025, 4, 1), "R. Aldrich", date(2026, 4, 1))


def span() -> Span:
    return Span(datetime(2025, 6, 1, 6), datetime(2025, 6, 11, 6))


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
                taken_at=datetime(2025, 6, 1, 6),
                observer="D. Yardley",
                head_feet=Decimal(head),
            ),
        ),
    )


def deliveries(far_head: str = "0.40") -> DeliveryLedger:
    return DeliveryLedger(
        span=span(),
        records=(
            record_for(NEAR, device(NEAR), series(NEAR, "0.60"), span()),
            record_for(FAR, device(FAR), series(FAR, far_head), span()),
        ),
    )


def ledger(*payments: Payment) -> AccountLedger:
    bill = bill_account(
        account=HOLDER,
        water_year=2025,
        issued_on=date(2025, 11, 1),
        schedule=RateSchedule(
            water_year=2025,
            per_share=Money.from_dollars("4.50"),
            bands=(Band(None, Money.from_dollars("2.00")),),
        ),
        shares=Decimal("20"),
        delivered_af=Decimal("50"),
    )
    return AccountLedger(account=HOLDER, bills=(bill,), payments=payments)


def statement(
    as_of: date = date(2025, 12, 15),
    far_head: str = "0.40",
    payments: tuple[Payment, ...] = (),
) -> Statement:
    return build(
        account=HOLDER,
        name="Alma Peterson",
        water_year=2025,
        shares=Decimal("20"),
        ledger=ledger(*payments),
        deliveries=deliveries(far_head),
        turnouts=(NEAR, FAR),
        charged_loss={NEAR: Decimal("4.5"), FAR: Decimal("7.25")},
        due_on=DUE,
        as_of=as_of,
    )


def test_the_statement_totals_the_water_and_the_loss() -> None:
    built = statement()
    assert built.delivered_af == deliveries().total_af
    assert built.loss_af == Decimal("11.75")
    assert built.charged_af == built.delivered_af + built.loss_af


def test_each_turnout_gets_a_line() -> None:
    built = statement()
    assert built.line_for(FAR).loss_af == Decimal("7.25")
    assert len(built.rows()) == 2


def test_a_turnout_that_is_not_on_the_statement_is_refused() -> None:
    with pytest.raises(PolicyError, match="not on this statement"):
        statement().line_for(TurnoutCode("L2-99"))


def test_a_clean_season_is_proved_all_through() -> None:
    built = statement()
    assert built.estimated_af == Decimal("0")
    assert built.unproved_turnouts == ()


def test_a_reading_past_the_rating_shows_on_the_statement() -> None:
    built = statement(far_head="1.40")
    assert built.estimated_af > Decimal("0")
    assert FAR in built.unproved_turnouts


def test_the_balance_and_the_penalty_come_off_the_ledger() -> None:
    built = statement()
    assert built.balance == Money.from_dollars("190.00")
    assert built.penalty == Money.zero()
    assert built.owed == built.balance


def test_a_late_account_carries_a_penalty() -> None:
    built = statement(as_of=date(2026, 3, 1))
    assert built.penalty.cents > 0
    assert built.owed > built.balance
    assert built.is_delinquent


def test_an_account_that_pays_is_in_good_standing() -> None:
    paid = statement(
        as_of=date(2026, 3, 1),
        payments=(Payment(HOLDER, date(2025, 11, 20), Money.from_dollars("190.00")),),
    )
    assert not paid.is_delinquent
    assert not paid.is_shut_off
    assert dict(paid.summary())["standing"] == "in good standing"


def test_a_long_unpaid_account_is_shut_off() -> None:
    built = statement(as_of=date(2026, 4, 1))
    assert built.is_shut_off
    assert dict(built.summary())["standing"] == "shut off"


def test_the_summary_names_the_account_and_the_year() -> None:
    summary = dict(statement().summary())
    assert "Alma Peterson" in summary["account"]
    assert summary["water year"] == "2025"
    assert "acre feet" in summary["delivered"]


def test_a_ledger_for_another_account_is_refused() -> None:
    with pytest.raises(PolicyError, match="cannot go on a statement"):
        build(
            account=AccountNumber(212),
            name="Ruth Larsen",
            water_year=2025,
            shares=Decimal("10"),
            ledger=ledger(),
            deliveries=deliveries(),
            turnouts=(NEAR,),
            charged_loss={},
            due_on=DUE,
            as_of=date(2025, 12, 15),
        )


def test_a_turnout_with_no_loss_charged_shows_none() -> None:
    built = build(
        account=HOLDER,
        name="Alma Peterson",
        water_year=2025,
        shares=Decimal("20"),
        ledger=ledger(),
        deliveries=deliveries(),
        turnouts=(NEAR,),
        charged_loss={},
        due_on=DUE,
        as_of=date(2025, 12, 15),
    )
    assert built.loss_af == Decimal("0")
    assert built.charged_af == built.delivered_af
