from datetime import date
from decimal import Decimal

import pytest

from headgate.assessment.billing import BillRun, bill_account
from headgate.assessment.tiers import Band, RateSchedule
from headgate.errors import PolicyError
from headgate.ids import AccountNumber, TurnoutCode
from headgate.money import Money
from headgate.report.board import build
from headgate.report.exceptions import Attention, ExceptionReport, Urgency
from headgate.report.season import SeasonReport, TurnoutLine

NEAR = TurnoutCode("MAIN-3")
FAR = TurnoutCode("L2-14")
HOLDER = AccountNumber(118)


def line(turnout: TurnoutCode, delivered: str, measured: str) -> TurnoutLine:
    return TurnoutLine(
        turnout=turnout,
        delivered_af=Decimal(delivered),
        measured_af=Decimal(measured),
        estimated_af=Decimal(delivered) - Decimal(measured),
        loss_af=Decimal("10"),
        unaccounted_hours=Decimal("0"),
    )


def season(measured: str = "300") -> SeasonReport:
    return SeasonReport(
        water_year=2025,
        district="Sanpete Ditch Company",
        headgate_af=Decimal("400"),
        lines=(
            line(NEAR, "200", measured if measured == "300" else measured),
            line(FAR, "100", "100"),
        ),
        expected_loss_af=Decimal("80"),
    )


def bills(water_year: int = 2025) -> BillRun:
    return BillRun(
        water_year=water_year,
        issued_on=date(water_year, 11, 1),
        bills=(
            bill_account(
                account=HOLDER,
                water_year=water_year,
                issued_on=date(water_year, 11, 1),
                schedule=RateSchedule(
                    water_year=water_year,
                    per_share=Money.from_dollars("6.00"),
                    bands=(Band(None, Money.from_dollars("2.00")),),
                ),
                shares=Decimal("20"),
                delivered_af=Decimal("50"),
            ),
        ),
    )


def quiet() -> ExceptionReport:
    return ExceptionReport(on=date(2025, 11, 1), exceptions=())


def noisy() -> ExceptionReport:
    return ExceptionReport(
        on=date(2025, 11, 1),
        exceptions=(Attention(Urgency.NOW, "L2-20", "nothing was measured", costs_water=True),),
    )


def test_a_clean_season_is_worth_adopting() -> None:
    packet = build(season("200"), bills(), quiet())
    assert packet.is_proved
    assert packet.can_be_adopted
    assert packet.reasons_not_to_adopt() == ()


def test_a_season_mostly_estimated_is_not_worth_adopting() -> None:
    packet = build(season("50"), bills(), quiet())
    assert not packet.is_proved
    assert not packet.can_be_adopted
    assert "proved" in packet.reasons_not_to_adopt()[0]


def test_an_exception_costing_water_stops_the_recommendation() -> None:
    packet = build(season("200"), bills(), noisy())
    assert packet.is_proved
    assert not packet.can_be_adopted
    assert "L2-20" in packet.reasons_not_to_adopt()[0]


def test_the_packet_carries_the_assessment() -> None:
    packet = build(season("200"), bills(), quiet())
    assert packet.accounts_billed == 1
    assert packet.billed.cents > 0


def test_the_summary_reads_in_the_order_it_is_argued_about() -> None:
    summary = [name for name, _ in build(season("200"), bills(), quiet()).summary()]
    assert summary[:4] == ["district", "water year", "headgate", "delivered"]
    assert summary[-1] == "recommend adopting"


def test_the_sections_carry_the_three_tables() -> None:
    sections = dict(build(season("200"), bills(), noisy()).sections())
    assert len(sections["deliveries"]) == 2
    assert len(sections["assessment"]) == 1
    assert len(sections["exceptions"]) == 1


def test_bills_from_another_year_cannot_go_in_the_packet() -> None:
    with pytest.raises(PolicyError, match="do not belong in"):
        build(season("200"), bills(2024), quiet())


def test_an_impossible_floor_is_refused() -> None:
    with pytest.raises(PolicyError, match="not a share of a season"):
        build(season("200"), bills(), quiet(), proved_floor=Decimal("1.5"))


def test_the_floor_can_be_lowered_for_a_bad_year() -> None:
    packet = build(season("50"), bills(), quiet(), proved_floor=Decimal("0.5"))
    assert packet.is_proved
    assert packet.can_be_adopted


def test_the_packet_counts_what_wants_attention() -> None:
    assert build(season("200"), bills(), noisy()).wants_attention == 1
    assert build(season("200"), bills(), quiet()).wants_attention == 0
