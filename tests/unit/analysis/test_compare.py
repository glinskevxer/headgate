from decimal import Decimal

import pytest

from headgate.analysis.compare import (
    SeasonTotals,
    average_delivery,
    compare,
)
from headgate.errors import PolicyError, ValidationError
from headgate.ids import TurnoutCode

NEAR = TurnoutCode("MAIN-3")
FAR = TurnoutCode("L2-14")


def season(year: int, headgate: str, near: str, far: str) -> SeasonTotals:
    delivered = Decimal(near) + Decimal(far)
    return SeasonTotals(
        water_year=year,
        headgate_af=Decimal(headgate),
        delivered_af=delivered,
        by_turnout={NEAR: Decimal(near), FAR: Decimal(far)},
    )


def test_a_season_reports_its_loss_and_carriage() -> None:
    totals = season(2024, "1000", "500", "300")
    assert totals.loss_af == Decimal("200")
    assert totals.carriage == Decimal("0.800")


def test_a_season_that_delivered_more_than_it_diverted_is_refused() -> None:
    with pytest.raises(PolicyError, match="more than the headgate passed"):
        SeasonTotals(2024, Decimal("100"), Decimal("200"), {})


def test_negative_water_is_refused() -> None:
    with pytest.raises(ValidationError, match="negative water"):
        SeasonTotals(2024, Decimal("-1"), Decimal("0"), {})


def test_a_season_with_no_headgate_has_no_carriage() -> None:
    assert SeasonTotals(2024, Decimal("0"), Decimal("0"), {}).carriage == Decimal("0")


def test_two_seasons_line_up_turnout_by_turnout() -> None:
    found = compare(season(2024, "1000", "500", "300"), season(2025, "800", "400", "240"))
    assert found.delivered_change == Decimal("-20.0")
    assert found.headgate_change == Decimal("-20.0")
    assert len(found.changes) == 2


def test_a_turnout_down_with_the_district_is_in_step() -> None:
    found = compare(season(2024, "1000", "500", "300"), season(2025, "800", "400", "240"))
    assert found.for_turnout(NEAR).against_the_district == Decimal("0.0")
    assert found.out_of_step() == ()


def test_a_turnout_down_on_its_own_is_out_of_step() -> None:
    found = compare(season(2024, "1000", "500", "300"), season(2025, "800", "500", "140"))
    assert [item.turnout for item in found.out_of_step()] == [FAR]
    assert found.for_turnout(FAR).against_the_district < Decimal("0")


def test_the_tolerance_can_be_tightened() -> None:
    found = compare(season(2024, "1000", "500", "300"), season(2025, "900", "480", "290"))
    assert found.out_of_step() == ()
    assert found.out_of_step(tolerance=Decimal("0.3"))


def test_a_negative_tolerance_is_refused() -> None:
    found = compare(season(2024, "1000", "500", "300"), season(2025, "800", "400", "240"))
    with pytest.raises(ValidationError, match="may not be negative"):
        found.for_turnout(NEAR).is_out_of_step(Decimal("-1"))


def test_a_turnout_that_only_ran_in_one_year_is_still_compared() -> None:
    before = SeasonTotals(2024, Decimal("500"), Decimal("300"), {NEAR: Decimal("300")})
    after = SeasonTotals(
        2025, Decimal("500"), Decimal("300"), {NEAR: Decimal("200"), FAR: Decimal("100")}
    )
    found = compare(before, after)
    assert found.for_turnout(FAR).before_af == Decimal("0")
    assert found.for_turnout(FAR).change == Decimal("0")


def test_the_years_have_to_run_forwards() -> None:
    with pytest.raises(PolicyError, match="does not come after"):
        compare(season(2025, "1000", "500", "300"), season(2024, "800", "400", "240"))


def test_a_turnout_that_was_in_neither_year_is_refused() -> None:
    found = compare(season(2024, "1000", "500", "300"), season(2025, "800", "400", "240"))
    with pytest.raises(PolicyError, match="not in this comparison"):
        found.for_turnout(TurnoutCode("L2-99"))


def test_the_loss_change_is_reported_on_its_own() -> None:
    found = compare(season(2024, "1000", "500", "300"), season(2025, "1000", "400", "240"))
    assert found.loss_change > Decimal("0")
    assert found.carriage_change < Decimal("0")


def test_the_summary_names_both_years() -> None:
    summary = dict(
        compare(season(2024, "1000", "500", "300"), season(2025, "800", "400", "240")).summary()
    )
    assert summary["years"] == "2024 to 2025"
    assert "percent" in summary["delivered"]


def test_the_average_delivery_runs_over_whatever_years_are_there() -> None:
    seasons = {
        2023: season(2023, "1000", "500", "300"),
        2024: season(2024, "1000", "400", "300"),
    }
    assert average_delivery(seasons, NEAR) == Decimal("450")


def test_an_average_of_no_seasons_is_refused() -> None:
    with pytest.raises(PolicyError, match="no seasons to average"):
        average_delivery({}, NEAR)
