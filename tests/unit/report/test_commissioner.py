from datetime import date, datetime
from decimal import Decimal

import pytest

from headgate.errors import PolicyError
from headgate.ids import DecreeNumber
from headgate.model.right import Priority, RightKind, RightStatus, WaterRight
from headgate.priority.curtail import CurtailmentNotice, CurtailmentRegister
from headgate.report.commissioner import build_day

DAY = date(2025, 7, 4)
MOMENT = datetime(2025, 7, 4, 12)


def right(
    sequence: int, year: int, rate: str, status: RightStatus = RightStatus.DECREED
) -> WaterRight:
    return WaterRight(
        decree=DecreeNumber(f"CDA-1920-{sequence}"),
        owner=f"Owner {sequence}",
        kind=RightKind.DIRECT_FLOW,
        priority=Priority(date(year, 5, 1), 1920, sequence),
        diversion_mile=Decimal("20"),
        rate_cfs=Decimal(rate),
        status=status,
    )


def rights() -> list[WaterRight]:
    return [right(5, 1901, "5"), right(1, 1873, "6"), right(4, 1895, "4")]


def taking(**amounts: str) -> dict[DecreeNumber, Decimal]:
    return {DecreeNumber(f"CDA-1920-{key[1:]}"): Decimal(value) for key, value in amounts.items()}


def register(allowed: str = "0") -> CurtailmentRegister:
    return CurtailmentRegister().issue(
        CurtailmentNotice(
            decree=DecreeNumber("CDA-1920-5"),
            called_by=DecreeNumber("CDA-1920-1"),
            issued_at=datetime(2025, 7, 1, 8),
            effective_at=datetime(2025, 7, 2, 8),
            curtailed_cfs=Decimal("5"),
            allowed_cfs=Decimal(allowed),
            reason="call by CDA-1920-1",
        )
    )


def test_the_report_runs_most_senior_first() -> None:
    report = build_day(DAY, rights(), taking(), CurtailmentRegister(), Decimal("20"), MOMENT)
    assert [line.decree.sequence for line in report.lines] == [1, 4, 5]


def test_an_abandoned_right_is_left_off() -> None:
    dead = [*rights(), right(9, 1910, "3", RightStatus.ABANDONED)]
    report = build_day(DAY, dead, taking(), CurtailmentRegister(), Decimal("20"), MOMENT)
    assert len(report.lines) == 3


def test_a_right_inside_its_decree_is_in_compliance() -> None:
    report = build_day(
        DAY, rights(), taking(d1="6", d4="4", d5="5"), CurtailmentRegister(), Decimal("20"), MOMENT
    )
    assert report.in_compliance
    assert report.over_diverting == ()


def test_a_right_over_its_decree_shows_up() -> None:
    report = build_day(DAY, rights(), taking(d1="8"), CurtailmentRegister(), Decimal("20"), MOMENT)
    line = report.line_for(DecreeNumber("CDA-1920-1"))
    assert line.is_over
    assert line.over_its_decree
    assert line.over_cfs == Decimal("2")


def test_a_curtailed_right_taking_water_is_over_without_being_over_its_decree() -> None:
    report = build_day(DAY, rights(), taking(d5="3"), register(), Decimal("20"), MOMENT)
    line = report.line_for(DecreeNumber("CDA-1920-5"))
    assert line.curtailed
    assert line.is_over
    assert not line.over_its_decree


def test_a_partial_curtailment_leaves_room_to_take_something() -> None:
    report = build_day(DAY, rights(), taking(d5="1"), register("2"), Decimal("20"), MOMENT)
    line = report.line_for(DecreeNumber("CDA-1920-5"))
    assert line.allowed_cfs == Decimal("2")
    assert not line.is_over
    assert line.unused_cfs == Decimal("1")


def test_a_notice_that_has_not_taken_effect_yet_does_not_bind() -> None:
    early = datetime(2025, 7, 1, 12)
    report = build_day(DAY, rights(), taking(d5="5"), register(), Decimal("20"), early)
    line = report.line_for(DecreeNumber("CDA-1920-5"))
    assert not line.curtailed
    assert not line.is_over


def test_the_report_totals_what_was_diverted_and_what_passed() -> None:
    report = build_day(
        DAY, rights(), taking(d1="6", d4="4"), CurtailmentRegister(), Decimal("20"), MOMENT
    )
    assert report.diverted_cfs == Decimal("10")
    assert report.passing_cfs == Decimal("10")


def test_a_creek_smaller_than_the_diversions_is_oversubscribed() -> None:
    report = build_day(
        DAY, rights(), taking(d1="6", d4="4", d5="5"), CurtailmentRegister(), Decimal("8"), MOMENT
    )
    assert report.oversubscribed
    assert report.passing_cfs == Decimal("0")


def test_the_curtailed_rights_are_listed() -> None:
    report = build_day(DAY, rights(), taking(), register(), Decimal("20"), MOMENT)
    assert [line.decree.sequence for line in report.curtailed] == [5]


def test_a_creek_cannot_run_backwards() -> None:
    with pytest.raises(PolicyError, match="run backwards"):
        build_day(DAY, rights(), taking(), CurtailmentRegister(), Decimal("-1"), MOMENT)


def test_asking_for_a_right_that_is_not_on_the_page_is_refused() -> None:
    report = build_day(DAY, rights(), taking(), CurtailmentRegister(), Decimal("20"), MOMENT)
    with pytest.raises(PolicyError, match="not on the report"):
        report.line_for(DecreeNumber("CDA-1920-9"))


def test_the_rows_carry_a_column_for_the_curtailment() -> None:
    rows = build_day(DAY, rights(), taking(d5="3"), register(), Decimal("20"), MOMENT).rows()
    assert rows[-1][-1] == "yes"
    assert rows[0][-1] == "no"


def test_the_summary_names_the_day_and_the_creek() -> None:
    summary = dict(
        build_day(DAY, rights(), taking(), CurtailmentRegister(), Decimal("20"), MOMENT).summary()
    )
    assert summary["day"] == "2025-07-04"
    assert "cfs" in summary["creek"]
