from datetime import date
from decimal import Decimal

import pytest

from headgate.errors import PolicyError, ValidationError
from headgate.ids import DitchCode
from headgate.model.seepage import SeepageHistory, SeepageRun

L2 = DitchCode("L2")


def run(
    inflow: str = "10",
    outflow: str = "9",
    turnouts: str = "0",
    length: str = "5280",
    on: date = date(2025, 5, 20),
) -> SeepageRun:
    return SeepageRun(
        ditch=L2,
        run_on=on,
        from_station_feet=Decimal("0"),
        to_station_feet=Decimal(length),
        inflow_cfs=Decimal(inflow),
        outflow_cfs=Decimal(outflow),
        turnouts_running_cfs=Decimal(turnouts),
    )


def test_a_run_measures_the_loss_between_the_two_flumes() -> None:
    assert run().loss_cfs == Decimal("1")
    assert run().length_miles == Decimal("1")


def test_water_running_to_turnouts_comes_off_the_loss() -> None:
    assert run(turnouts="2").loss_cfs == Decimal("-1")


def test_a_run_that_ends_above_where_it_started_is_refused() -> None:
    with pytest.raises(ValidationError, match="not below"):
        SeepageRun(
            ditch=L2,
            run_on=date(2025, 5, 20),
            from_station_feet=Decimal("5280"),
            to_station_feet=Decimal("0"),
            inflow_cfs=Decimal("10"),
            outflow_cfs=Decimal("9"),
        )


def test_a_run_with_no_water_in_the_ditch_is_refused() -> None:
    with pytest.raises(ValidationError, match="no water in the ditch"):
        run(inflow="0")


def test_negative_flows_are_refused() -> None:
    with pytest.raises(ValidationError, match="negative flow"):
        run(outflow="-1")


def test_a_clean_run_is_credible() -> None:
    assert run().is_credible
    assert run().why_not() == ()


def test_a_run_with_the_turnouts_open_is_not_credible() -> None:
    found = run(turnouts="0.5", outflow="8.5")
    assert not found.turnouts_were_shut
    assert not found.is_credible
    assert "running to turnouts" in found.why_not()[0]


def test_a_loss_inside_the_error_band_is_not_measurable() -> None:
    found = run(outflow="9.95")
    assert not found.is_measurable
    assert "the flumes could be wrong by" in found.why_not()[0]


def test_a_short_reach_is_not_worth_measuring_over() -> None:
    found = run(length="500")
    assert not found.is_long_enough
    assert "too short a reach" in found.why_not()[-1]


def test_a_gaining_reach_is_a_real_measurement() -> None:
    found = run(outflow="11")
    assert found.is_gaining
    assert found.loss_cfs < Decimal("0")
    assert found.is_credible


def test_the_loss_comes_out_as_a_fraction_a_mile() -> None:
    assert run().loss_fraction_per_mile == Decimal("0.1000")
    assert run(length="10560").loss_fraction_per_mile == Decimal("0.0500")


def test_a_history_keeps_the_runs_in_order() -> None:
    with pytest.raises(ValidationError, match="out of order"):
        SeepageHistory(L2, (run(on=date(2025, 6, 1)), run(on=date(2025, 5, 1))))


def test_a_history_holds_one_ditch() -> None:
    other = SeepageRun(
        ditch=DitchCode("MAIN"),
        run_on=date(2025, 5, 20),
        from_station_feet=Decimal("0"),
        to_station_feet=Decimal("5280"),
        inflow_cfs=Decimal("10"),
        outflow_cfs=Decimal("9"),
    )
    with pytest.raises(ValidationError, match="turned up in the history"):
        SeepageHistory(L2, (other,))


def test_the_rate_comes_out_of_the_runs_worth_using() -> None:
    history = SeepageHistory(
        L2,
        (
            run(on=date(2025, 5, 1)),
            run(outflow="9.95", on=date(2025, 6, 1)),
            run(outflow="8.8", on=date(2025, 7, 1)),
        ),
    )
    assert len(history.credible) == 2
    assert history.measured_loss_per_mile() > Decimal("0.1")


def test_a_gaining_run_is_kept_but_not_used_for_the_rate() -> None:
    history = SeepageHistory(L2, (run(on=date(2025, 5, 1)), run(outflow="11", on=date(2025, 6, 1))))
    assert len(history.gaining) == 1
    assert history.measured_loss_per_mile() == Decimal("0.1000")


def test_a_ditch_with_no_usable_run_sets_no_rate() -> None:
    history = SeepageHistory(L2, (run(outflow="9.95"),))
    with pytest.raises(PolicyError, match="worth setting a loss rate from"):
        history.measured_loss_per_mile()


def test_a_ditch_losing_more_than_the_book_says_is_flagged() -> None:
    history = SeepageHistory(L2, (run(),))
    assert history.has_got_worse(Decimal("0.05"))
    assert not history.has_got_worse(Decimal("0.12"))


def test_a_negative_tolerance_is_refused() -> None:
    history = SeepageHistory(L2, (run(),))
    with pytest.raises(ValidationError, match="may not be negative"):
        history.has_got_worse(Decimal("0.05"), tolerance=Decimal("-1"))


def test_the_latest_run_is_the_last_one() -> None:
    history = SeepageHistory(L2, (run(on=date(2025, 5, 1)), run(on=date(2025, 7, 1))))
    assert history.latest().run_on == date(2025, 7, 1)
    with pytest.raises(PolicyError, match="nobody has run"):
        SeepageHistory(L2).latest()
