"""A dry year, from the April forecast to the notices on the juniors.

The pieces are all tested on their own. What this checks is that they agree
with each other: that the forecast the board plans on becomes an allotment a
share, that the allotment holds the orders down, that a senior right short of
water gets its juniors shut, and that the notices it produces are the same
notices the order intake then reads back.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

import pytest

from headgate.duty.allotment import allot
from headgate.forecast.supply import Exceedance, Forecast, ForecastSeries, supply_from
from headgate.ids import AccountNumber, DecreeNumber, TurnoutCode
from headgate.model.order import WaterOrder
from headgate.model.right import Priority, RightKind, WaterRight
from headgate.model.stream import Reach, Stream
from headgate.orders.intake import IntakeRules, answer_order
from headgate.priority.call import Call, CallOutcome, evaluate_call
from headgate.priority.curtail import notices_from
from headgate.store.db import Database
from headgate.store.repo_accounts import load_register
from headgate.store.repo_curtail import load_register as load_notices
from headgate.store.repo_curtail import serve_notice, standing_at
from headgate.store.repo_ditch import load_stream, load_system, save_stream
from headgate.store.repo_orders import load_book
from headgate.store.repo_rights import load_active_ladder, save_right
from headgate.store.repo_season import load_season
from headgate.wateryear import IrrigationSeason, Span
from tests.support.district import (
    HOLDER,
    SECOND_HOLDER,
    TURNOUT,
    init_book,
    lateral,
    must,
    run,
    shareholders,
    stock,
)

SENIOR = DecreeNumber("CDA-1920-1")
JUNIOR = DecreeNumber("CDA-1920-5")
NOON = datetime(2025, 7, 4, 12)


def right(decree: DecreeNumber, sequence: int, year: int, mile: str, cfs: str) -> WaterRight:
    return WaterRight(
        decree=decree,
        owner=f"Owner {sequence}",
        kind=RightKind.DIRECT_FLOW,
        priority=Priority(date(year, 5, 1), 1920, sequence),
        diversion_mile=Decimal(mile),
        rate_cfs=Decimal(cfs),
    )


def creek() -> Stream:
    return Stream(
        name="Sanpete Creek",
        reaches=(
            Reach("R1", "Upper", Decimal("40"), Decimal("20"), Decimal("2"), Decimal("0.01")),
            Reach("R2", "Lower", Decimal("20"), Decimal("4"), Decimal("3"), Decimal("0.01")),
        ),
    )


def forecast(median: str) -> Forecast:
    middle = Decimal(median)
    return Forecast(
        water_year=2025,
        issued_on=date(2025, 4, 1),
        source="Sanpete basin forecast",
        volumes_af={
            Exceedance.WET: middle * Decimal("1.4"),
            Exceedance.LIKELY: middle * Decimal("1.15"),
            Exceedance.MEDIAN: middle,
            Exceedance.DRY: middle * Decimal("0.85"),
            Exceedance.CRITICAL: middle * Decimal("0.6"),
        },
    )


@pytest.fixture
def district(tmp_path: Path) -> Path:
    book = stock(init_book(tmp_path / "district.sqlite3"), lateral(), shareholders("30", "10"))
    with Database(book).open() as connection:
        save_stream(connection, creek())
        save_right(connection, right(SENIOR, 1, 1873, "10", "6"))
        save_right(connection, right(JUNIOR, 5, 1901, "30", "5"))
    must(
        book,
        [
            "season",
            "declare",
            "--year",
            "2025",
            "--opens",
            "2025-04-15",
            "--closes",
            "2025-10-01",
            "--declared",
            "2025-03-20",
        ],
    )
    return book


def test_a_dry_forecast_makes_a_small_allotment(district: Path) -> None:
    dry = supply_from(forecast("4000"), Exceedance.DRY, Decimal("200"), Decimal("0.15"))
    wet = supply_from(forecast("9000"), Exceedance.DRY, Decimal("200"), Decimal("0.15"))
    with Database(district).open() as connection:
        register = load_register(connection)
        shares = {
            holder.number: register.shares_of(holder.number, date(2025, 4, 15))
            for holder in register.accounts
        }
    lean = allot(2025, dry.deliverable_af, shares, date(2025, 4, 1), dry.basis)
    fat = allot(2025, wet.deliverable_af, shares, date(2025, 4, 1), wet.basis)
    assert lean.allotment.af_per_share < fat.allotment.af_per_share
    assert lean.allowed_af(HOLDER) > lean.allowed_af(SECOND_HOLDER)


def test_a_forecast_that_came_in_later_supersedes_the_april_one(district: Path) -> None:
    series = (
        ForecastSeries(2025)
        .add(forecast("8000"))
        .add(
            Forecast(
                water_year=2025,
                issued_on=date(2025, 6, 1),
                source="Sanpete basin forecast",
                volumes_af=forecast("5000").volumes_af,
            )
        )
    )
    assert series.current_on(date(2025, 6, 15)).median_af == Decimal("5000")


def test_an_order_is_cut_to_what_the_curtailment_allows(district: Path) -> None:
    with Database(district).open() as connection:
        season = load_season(connection, 2025)
        register = load_register(connection)
        system = load_system(connection)
        order = WaterOrder(
            order_id=1,
            account=HOLDER,
            turnout=TURNOUT,
            requested_cfs=Decimal("5"),
            span=Span(datetime(2025, 7, 1, 6), datetime(2025, 7, 8, 6)),
            placed_at=datetime(2025, 6, 28, 8),
        )
        answered = answer_order(
            order,
            IntakeRules(),
            register,
            season,
            system,
            load_book(connection, order.span),
            curtailed_to=Decimal("1.5"),
        )
    assert answered.allowed_cfs == Decimal("1.5")
    assert "curtailment" in answered.note


def test_a_call_shuts_the_junior_and_the_notice_lands_in_the_book(district: Path) -> None:
    with Database(district).open() as connection:
        stream = load_stream(connection, "Sanpete Creek")
        ladder = load_active_ladder(connection)
        calling = next(item for item in ladder if item.decree == SENIOR)
        decision = evaluate_call(
            stream,
            ladder,
            Call(decree_owner=calling, placed_at=NOON),
            {JUNIOR: Decimal("5")},
            Decimal("2"),
        )
        assert decision.outcome is CallOutcome.HONOURED
        for notice in notices_from(decision, NOON):
            serve_notice(connection, notice)
        standing = standing_at(connection, datetime(2025, 7, 6, 12))
        allowed = load_notices(connection).allowed_rate(JUNIOR, datetime(2025, 7, 6, 12))
    assert [item.decree for item in standing] == [JUNIOR]
    assert allowed is not None
    assert allowed < Decimal("5")


def test_the_same_call_read_back_through_the_command_line(district: Path) -> None:
    code, output = run(
        district,
        [
            "call",
            "place",
            "--decree",
            "CDA-1920-1",
            "--arriving",
            "2",
            "--taking",
            "CDA-1920-5=5",
            "--at",
            "2025-07-04T12:00",
            "--stream",
            "Sanpete Creek",
            "--serve",
        ],
    )
    assert code == 0
    assert "honoured" in output
    code, output = run(district, ["call", "standing", "--at", "2025-07-06T12:00"])
    assert "CDA-1920-5" in output


def test_a_call_that_cannot_reach_in_time_is_refused(district: Path) -> None:
    code, output = run(
        district,
        [
            "call",
            "place",
            "--decree",
            "CDA-1920-1",
            "--arriving",
            "2",
            "--taking",
            "CDA-1920-5=5",
            "--at",
            "2025-07-04T12:00",
            "--needed-by",
            "2025-07-04T12:30",
            "--stream",
            "Sanpete Creek",
        ],
    )
    assert code == 0
    assert "futile" in output
    code, output = run(district, ["call", "standing", "--at", "2025-07-06T12:00"])
    assert "nothing was curtailed" in output


def test_lifting_the_call_puts_the_junior_back_on(district: Path) -> None:
    run(
        district,
        [
            "call",
            "place",
            "--decree",
            "CDA-1920-1",
            "--arriving",
            "2",
            "--taking",
            "CDA-1920-5=5",
            "--at",
            "2025-07-04T12:00",
            "--stream",
            "Sanpete Creek",
            "--serve",
        ],
    )
    must(district, ["call", "lift", "--decree", "CDA-1920-1", "--at", "2025-07-20T08:00"])
    with Database(district).open() as connection:
        allowed = load_notices(connection).allowed_rate(JUNIOR, datetime(2025, 7, 21, 12))
    assert allowed is None


def test_the_season_the_call_was_placed_in_is_the_declared_one(district: Path) -> None:
    with Database(district).open() as connection:
        season = load_season(connection, 2025)
    assert season == IrrigationSeason.default_for(2025)
    assert season.covers(NOON.date())


def test_a_turnout_that_never_ran_is_still_on_the_gaps_report(district: Path) -> None:
    code, output = run(district, ["report", "gaps", "2025"])
    assert code == 0
    assert str(TurnoutCode("L2-14")) in output


def test_the_shareholders_are_where_the_allotment_expects_them(district: Path) -> None:
    with Database(district).open() as connection:
        register = load_register(connection)
    assert register.shares_at(TURNOUT, date(2025, 4, 15)) == Decimal("40")
    assert register.shares_of(AccountNumber(118), date(2025, 4, 15)) == Decimal("30")
