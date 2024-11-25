from datetime import date
from decimal import Decimal

import pytest

from headgate.errors import PolicyError, ValidationError
from headgate.ids import DecreeNumber
from headgate.wells.depletion import (
    PumpingRecord,
    Well,
    augmentation_owed,
    check_annual_limit,
    depletion_by_month,
    depletion_fraction,
    stream_depletion_factor,
)


def well(distance: str = "1500", limit: str | None = None) -> Well:
    return Well(
        well_id="W-14",
        decree=DecreeNumber("CDA-1972-14"),
        distance_to_stream_feet=Decimal(distance),
        storativity=Decimal("0.15"),
        transmissivity_ft2_day=Decimal("15000"),
        capacity_gpm=Decimal("900"),
        annual_limit_af=Decimal(limit) if limit is not None else None,
    )


def test_the_factor_grows_with_the_square_of_the_distance() -> None:
    near = stream_depletion_factor(Decimal("500"), Decimal("0.15"), Decimal("15000"))
    far = stream_depletion_factor(Decimal("1000"), Decimal("0.15"), Decimal("15000"))
    assert far == near * 4


def test_a_looser_aquifer_gives_a_smaller_factor() -> None:
    tight = stream_depletion_factor(Decimal("1500"), Decimal("0.15"), Decimal("5000"))
    loose = stream_depletion_factor(Decimal("1500"), Decimal("0.15"), Decimal("30000"))
    assert loose < tight


def test_a_well_in_the_stream_is_not_a_well() -> None:
    with pytest.raises(ValidationError, match="not a well"):
        stream_depletion_factor(Decimal("0"), Decimal("0.15"), Decimal("15000"))


def test_an_impossible_aquifer_is_refused() -> None:
    with pytest.raises(ValidationError, match="not an aquifer"):
        stream_depletion_factor(Decimal("1500"), Decimal("1.5"), Decimal("15000"))
    with pytest.raises(ValidationError, match="moves no water"):
        stream_depletion_factor(Decimal("1500"), Decimal("0.15"), Decimal("0"))


def test_depletion_starts_at_nothing_and_climbs() -> None:
    assert depletion_fraction(Decimal("0"), Decimal("30")) == Decimal("0")
    early = depletion_fraction(Decimal("10"), Decimal("30"))
    late = depletion_fraction(Decimal("400"), Decimal("30"))
    assert early < late
    assert late > Decimal("0.8")


def test_depletion_never_reaches_the_whole_of_the_pumping() -> None:
    assert depletion_fraction(Decimal("10000"), Decimal("30")) <= Decimal("1")


def test_a_distant_well_is_still_depleting_years_later() -> None:
    close = depletion_fraction(Decimal("180"), Decimal("30"))
    distant = depletion_fraction(Decimal("180"), Decimal("4000"))
    assert distant < close
    assert distant < Decimal("0.1")


def test_depletion_is_not_worked_backwards() -> None:
    with pytest.raises(ValidationError, match="backwards in time"):
        depletion_fraction(Decimal("-1"), Decimal("30"))


def test_a_factor_of_nothing_is_refused() -> None:
    with pytest.raises(ValidationError, match="not a factor"):
        depletion_fraction(Decimal("30"), Decimal("0"))


def test_a_well_by_the_bridge_is_administered_like_a_diversion() -> None:
    assert well("200").is_close_to_the_stream
    assert not well("3000").is_close_to_the_stream


def test_a_well_needs_an_identifier_and_a_pump() -> None:
    with pytest.raises(ValidationError, match="needs an identifier"):
        Well(
            "  ",
            DecreeNumber("CDA-1972-14"),
            Decimal("1500"),
            Decimal("0.15"),
            Decimal("15000"),
            Decimal("900"),
        )
    with pytest.raises(ValidationError, match="pumps nothing"):
        Well(
            "W-14",
            DecreeNumber("CDA-1972-14"),
            Decimal("1500"),
            Decimal("0.15"),
            Decimal("15000"),
            Decimal("0"),
        )


def test_a_well_limited_to_nothing_is_refused() -> None:
    with pytest.raises(ValidationError, match="no water at all"):
        well(limit="0")


def test_the_pump_capacity_comes_out_in_acre_feet() -> None:
    assert well().season_capacity_af(Decimal("30")) > Decimal("100")


def test_depletion_from_a_months_pumping_is_less_than_the_pumping() -> None:
    depleted = well().depletion_from(Decimal("100"), Decimal("60"))
    assert Decimal("0") < depleted < Decimal("100")


def test_a_negative_pumping_volume_is_refused() -> None:
    with pytest.raises(ValidationError, match="negative volume"):
        well().depletion_from(Decimal("-1"), Decimal("60"))


def records() -> list[PumpingRecord]:
    return [
        PumpingRecord(well(), 5, Decimal("40")),
        PumpingRecord(well(), 6, Decimal("60")),
        PumpingRecord(well(), 7, Decimal("80")),
    ]


def test_a_month_is_a_month() -> None:
    with pytest.raises(ValidationError, match="not a month"):
        PumpingRecord(well(), 13, Decimal("40"))
    with pytest.raises(ValidationError, match="not a month"):
        depletion_by_month(records(), 0)


def test_earlier_pumping_has_depleted_more_by_now() -> None:
    found = depletion_by_month(records(), 8)
    assert found[5] > found[7] * Decimal("0.5")


def test_pumping_after_the_month_asked_about_is_left_out() -> None:
    found = depletion_by_month(records(), 6)
    assert set(found) == {5, 6}


def test_the_augmentation_owed_is_the_depletion_not_yet_replaced() -> None:
    owed = augmentation_owed(records(), 8)
    assert owed > Decimal("0")
    assert owed < Decimal("180")


def test_replacing_water_takes_it_off_what_is_owed() -> None:
    owed = augmentation_owed(records(), 8)
    less = augmentation_owed(records(), 8, replaced_af=owed / 2)
    assert less < owed


def test_replacing_more_than_is_owed_leaves_nothing_owed() -> None:
    assert augmentation_owed(records(), 8, replaced_af=Decimal("500")) == Decimal("0")


def test_a_negative_replacement_is_refused() -> None:
    with pytest.raises(ValidationError, match="may not be negative"):
        augmentation_owed(records(), 8, replaced_af=Decimal("-1"))


def test_a_year_over_the_decreed_limit_is_refused() -> None:
    assert check_annual_limit(well(limit="200"), Decimal("180")) == Decimal("180.0000")
    with pytest.raises(PolicyError, match="against a limit"):
        check_annual_limit(well(limit="200"), Decimal("240"))


def test_a_well_with_no_limit_pumps_what_it_pumps() -> None:
    assert check_annual_limit(well(), Decimal("400")) == Decimal("400.0000")


def test_a_pumping_record_carries_the_wells_own_factor() -> None:
    record = PumpingRecord(well("3000"), 5, Decimal("40"))
    assert record.well.factor_days > well("1500").factor_days
    assert date(2025, 5, 1).month == record.month
