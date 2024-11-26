from decimal import Decimal

import pytest

from headgate.errors import PolicyError, ValidationError
from headgate.ids import DecreeNumber
from headgate.wells.augmentation import (
    AugmentationPlan,
    MonthMatch,
    ReplacementSource,
    SourceKind,
    require_cover,
)
from headgate.wells.depletion import PumpingRecord, Well


def well() -> Well:
    return Well(
        well_id="W-14",
        decree=DecreeNumber("CDA-1972-14"),
        distance_to_stream_feet=Decimal("800"),
        storativity=Decimal("0.15"),
        transmissivity_ft2_day=Decimal("15000"),
        capacity_gpm=Decimal("900"),
    )


def records() -> list[PumpingRecord]:
    return [
        PumpingRecord(well(), 6, Decimal("40")),
        PumpingRecord(well(), 7, Decimal("60")),
        PumpingRecord(well(), 8, Decimal("50")),
    ]


def source(
    name: str = "Ephraim storage",
    mile: str = "26",
    monthly: dict[int, str] | None = None,
    committed: bool = False,
    kind: SourceKind = SourceKind.STORAGE_RELEASE,
) -> ReplacementSource:
    volumes = monthly or {6: "40", 7: "60", 8: "60", 9: "40"}
    return ReplacementSource(
        name=name,
        kind=kind,
        delivery_mile=Decimal(mile),
        monthly_af={month: Decimal(value) for month, value in volumes.items()},
        committed_elsewhere=committed,
    )


def plan(*sources: ReplacementSource, mile: str = "22") -> AugmentationPlan:
    return AugmentationPlan(
        name="Peterson plan",
        depletion_mile=Decimal(mile),
        sources=sources or (source(),),
    )


def test_a_source_needs_a_name_and_real_months() -> None:
    with pytest.raises(ValidationError, match="needs a name"):
        source(name="  ")
    with pytest.raises(ValidationError, match="not a month"):
        ReplacementSource("lease", SourceKind.LEASE, Decimal("26"), {13: Decimal("10")})
    with pytest.raises(ValidationError, match="negative volume"):
        ReplacementSource("lease", SourceKind.LEASE, Decimal("26"), {6: Decimal("-1")})


def test_a_source_totals_its_year() -> None:
    assert source().annual_af == Decimal("200")


def test_water_committed_to_another_plan_is_not_available() -> None:
    assert source(committed=True).available_in(6) == Decimal("0")
    assert source().available_in(6) == Decimal("40")


def test_a_source_below_the_depletion_does_not_reach_it() -> None:
    assert source(mile="26").reaches(Decimal("22"))
    assert not source(mile="18").reaches(Decimal("22"))


def test_a_credit_is_a_different_sort_of_source() -> None:
    assert SourceKind.RECHARGE_CREDIT.is_a_credit
    assert not SourceKind.STORAGE_RELEASE.is_a_credit


def test_a_plan_needs_a_name_and_no_repeated_source() -> None:
    with pytest.raises(ValidationError, match="needs a name"):
        AugmentationPlan("  ", Decimal("22"), ())
    with pytest.raises(ValidationError, match="twice"):
        AugmentationPlan("Peterson plan", Decimal("22"), (source(), source()))


def test_a_source_that_lands_downstream_is_left_out() -> None:
    built = plan(source(mile="18"))
    assert built.usable_sources == ()
    assert len(built.out_of_place) == 1
    assert built.available_in(7) == Decimal("0")


def test_a_generous_plan_covers_every_month() -> None:
    assert plan().covers(records(), 9)
    assert plan().shortfall(records(), 9) == Decimal("0")
    assert plan().first_short_month(records(), 9) is None


def test_a_plan_with_nothing_in_august_is_short_in_august() -> None:
    thin = plan(source(monthly={6: "40", 7: "60", 9: "80"}))
    assert not thin.covers(records(), 9)
    assert thin.first_short_month(records(), 9) == 8
    assert thin.shortfall(records(), 9) > Decimal("0")


def test_a_surplus_in_one_month_does_not_carry_into_the_next() -> None:
    lumpy = plan(source(monthly={6: "400"}))
    matches = {item.month: item for item in lumpy.match(records(), 9)}
    assert matches[6].surplus_af > Decimal("0")
    assert not matches[7].is_covered


def test_two_sources_add_up_in_a_month() -> None:
    both = plan(
        source(monthly={8: "20"}),
        source(name="Larsen lease", kind=SourceKind.LEASE, monthly={8: "40"}),
    )
    assert both.available_in(8) == Decimal("60")


def test_a_match_reports_the_shortfall_and_the_surplus() -> None:
    match = MonthMatch(month=8, owed_af=Decimal("40"), replaced_af=Decimal("25"))
    assert match.shortfall_af == Decimal("15")
    assert match.surplus_af == Decimal("0")
    assert not match.is_covered


def test_months_nobody_pumped_or_replaced_are_left_off() -> None:
    months = [item.month for item in plan().match(records(), 9)]
    assert 1 not in months
    assert 6 in months


def test_a_caller_about_to_approve_insists_the_plan_covers() -> None:
    good = plan()
    assert require_cover(good, records(), 9) is good
    thin = plan(source(monthly={6: "40"}))
    with pytest.raises(PolicyError, match="is short"):
        require_cover(thin, records(), 9)


def test_committing_a_source_elsewhere_can_break_a_plan() -> None:
    working = plan(source())
    assert working.covers(records(), 9)
    broken = plan(source(committed=True))
    assert not broken.covers(records(), 9)
