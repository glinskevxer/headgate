from datetime import date
from decimal import Decimal

import pytest

from headgate.errors import PolicyError, ValidationError
from headgate.forecast.supply import (
    Exceedance,
    Forecast,
    ForecastSeries,
    Supply,
    supply_from,
)


def forecast(median: str = "8000", issued: date = date(2025, 4, 1)) -> Forecast:
    middle = Decimal(median)
    return Forecast(
        water_year=2025,
        issued_on=issued,
        source="Sanpete basin forecast",
        volumes_af={
            Exceedance.WET: middle * Decimal("1.4"),
            Exceedance.LIKELY: middle * Decimal("1.15"),
            Exceedance.MEDIAN: middle,
            Exceedance.DRY: middle * Decimal("0.85"),
            Exceedance.CRITICAL: middle * Decimal("0.6"),
        },
    )


def test_a_forecast_reads_at_each_exceedance() -> None:
    assert forecast().at(Exceedance.MEDIAN) == Decimal("8000")
    assert forecast().at(Exceedance.CRITICAL) < forecast().at(Exceedance.MEDIAN)


def test_a_forecast_says_who_issued_it() -> None:
    with pytest.raises(ValidationError, match="says who issued it"):
        Forecast(2025, date(2025, 4, 1), "  ", forecast().volumes_af)


def test_a_forecast_missing_a_level_is_refused() -> None:
    volumes = dict(forecast().volumes_af)
    del volumes[Exceedance.DRY]
    with pytest.raises(ValidationError, match="no 70 percent number"):
        Forecast(2025, date(2025, 4, 1), "basin forecast", volumes)


def test_a_backwards_forecast_is_refused() -> None:
    volumes = dict(forecast().volumes_af)
    volumes[Exceedance.CRITICAL] = Decimal("99999")
    with pytest.raises(ValidationError, match="backwards"):
        Forecast(2025, date(2025, 4, 1), "basin forecast", volumes)


def test_a_negative_forecast_is_refused() -> None:
    volumes = dict(forecast().volumes_af)
    volumes[Exceedance.CRITICAL] = Decimal("-1")
    with pytest.raises(ValidationError, match="negative runoff"):
        Forecast(2025, date(2025, 4, 1), "basin forecast", volumes)


def test_the_spread_is_the_wet_number_less_the_critical_one() -> None:
    assert forecast().spread_af > Decimal("0")


def test_a_dry_year_is_well_under_average() -> None:
    assert forecast("5000").is_dry_year(Decimal("10000"))
    assert not forecast("9000").is_dry_year(Decimal("10000"))


def test_the_forecast_is_reported_as_a_percentage_of_average() -> None:
    assert forecast("8000").percent_of_average(Decimal("10000")) == Decimal("80.0")


def test_an_average_of_nothing_is_not_an_average() -> None:
    with pytest.raises(ValidationError, match="not an average"):
        forecast().percent_of_average(Decimal("0"))
    with pytest.raises(ValidationError, match="not an average"):
        forecast().is_dry_year(Decimal("0"))


def series() -> ForecastSeries:
    return (
        ForecastSeries(water_year=2025)
        .add(forecast("8000", date(2025, 4, 1)))
        .add(forecast("6500", date(2025, 5, 1)))
        .add(forecast("5200", date(2025, 6, 1)))
    )


def test_the_series_keeps_the_forecasts_in_order() -> None:
    assert [item.issued_on.month for item in series().forecasts] == [4, 5, 6]


def test_the_forecast_that_stood_on_a_day_is_the_latest_one_issued() -> None:
    assert series().current_on(date(2025, 5, 20)).median_af == Decimal("6500")
    assert series().latest.median_af == Decimal("5200")


def test_asking_before_the_first_forecast_is_refused() -> None:
    with pytest.raises(PolicyError, match="no forecast had been issued"):
        series().current_on(date(2025, 3, 1))


def test_an_empty_series_has_no_latest() -> None:
    with pytest.raises(PolicyError, match="no forecast has been issued"):
        _ = ForecastSeries(water_year=2025).latest


def test_a_superseded_forecast_is_refused() -> None:
    with pytest.raises(PolicyError, match="was superseded by"):
        series().check_current(forecast("8000", date(2025, 4, 1)), date(2025, 6, 15))


def test_the_current_forecast_passes_the_check() -> None:
    current = forecast("5200", date(2025, 6, 1))
    assert series().check_current(current, date(2025, 6, 15)) is current


def test_a_forecast_for_another_year_cannot_join_the_series() -> None:
    other = Forecast(2024, date(2024, 4, 1), "basin forecast", forecast().volumes_af)
    with pytest.raises(ValidationError, match="turned up in the"):
        ForecastSeries(water_year=2025, forecasts=(other,))


def test_two_forecasts_on_one_day_are_refused() -> None:
    with pytest.raises(ValidationError, match="two forecasts one day"):
        ForecastSeries(
            water_year=2025,
            forecasts=(forecast("8000"), forecast("7000")),
        )


def test_the_supply_adds_carryover_and_takes_the_shrink_off() -> None:
    supply = supply_from(forecast(), Exceedance.DRY, Decimal("1200"), Decimal("0.15"))
    assert supply.gross_af == Decimal("8000") * Decimal("0.85") + Decimal("1200")
    assert supply.shrink_af > Decimal("0")
    assert supply.deliverable_af == supply.gross_af - supply.shrink_af


def test_the_supply_says_what_it_was_built_from() -> None:
    supply = supply_from(forecast(), Exceedance.DRY, Decimal("0"), Decimal("0.1"))
    assert "70 percent exceedance" in supply.basis
    assert "2025-04-01" in supply.basis


def test_a_conservative_district_promises_less() -> None:
    careful = supply_from(forecast(), Exceedance.CRITICAL, Decimal("0"), Decimal("0.15"))
    hopeful = supply_from(forecast(), Exceedance.WET, Decimal("0"), Decimal("0.15"))
    assert careful.deliverable_af < hopeful.deliverable_af
    assert Exceedance.CRITICAL.is_conservative
    assert not Exceedance.WET.is_conservative


def test_a_negative_supply_is_refused() -> None:
    with pytest.raises(ValidationError, match="negative water"):
        Supply(2025, Decimal("-1"), Decimal("0"), Decimal("0.1"), "nothing")


def test_a_shrink_that_loses_everything_is_refused() -> None:
    with pytest.raises(ValidationError, match="lose the whole supply"):
        Supply(2025, Decimal("100"), Decimal("0"), Decimal("1"), "nothing")
