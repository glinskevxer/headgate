from decimal import Decimal

import pytest

from headgate.errors import ValidationError
from headgate.model.stream import GagePoint, Reach, Stream


def reach(code: str, head: str, toe: str, velocity: str = "2", loss: str = "0.01") -> Reach:
    return Reach(
        code=code,
        name=f"{code} reach",
        head_mile=Decimal(head),
        toe_mile=Decimal(toe),
        mean_velocity_fps=Decimal(velocity),
        loss_fraction_per_mile=Decimal(loss),
    )


def stream() -> Stream:
    return Stream(
        name="Sanpete Creek",
        reaches=(reach("R1", "30", "22"), reach("R2", "22", "14", "4"), reach("R3", "14", "6")),
    )


def test_a_reach_knows_its_length_and_travel_time() -> None:
    piece = reach("R1", "30", "22", "2")
    assert piece.length_miles == Decimal("8")
    assert piece.travel_seconds == Decimal("21120")


def test_a_reach_may_not_run_uphill() -> None:
    with pytest.raises(ValidationError, match="upstream of where it started"):
        reach("R1", "22", "30")


def test_a_reach_with_no_velocity_is_refused() -> None:
    with pytest.raises(ValidationError, match="no velocity"):
        reach("R1", "30", "22", "0")


def test_an_absurd_loss_rate_is_refused() -> None:
    with pytest.raises(ValidationError, match="loss rate"):
        reach("R1", "30", "22", "2", "0.6")


def test_a_reach_contains_its_head_and_not_its_toe() -> None:
    piece = reach("R1", "30", "22")
    assert piece.contains(Decimal("22"))
    assert not piece.contains(Decimal("30"))


def test_a_stream_needs_reaches() -> None:
    with pytest.raises(ValidationError, match="no reaches"):
        Stream(name="Dry Wash", reaches=())


def test_a_stream_refuses_a_gap_between_reaches() -> None:
    with pytest.raises(ValidationError, match="leaving a gap"):
        Stream(name="Sanpete Creek", reaches=(reach("R1", "30", "22"), reach("R2", "20", "14")))


def test_a_stream_refuses_the_same_reach_twice() -> None:
    with pytest.raises(ValidationError, match="twice"):
        Stream(name="Sanpete Creek", reaches=(reach("R1", "30", "22"), reach("R1", "22", "14")))


def test_a_stream_reports_its_ends() -> None:
    creek = stream()
    assert creek.head_mile == Decimal("30")
    assert creek.toe_mile == Decimal("6")


def test_a_mile_finds_the_reach_it_sits_in() -> None:
    assert stream().reach_at(Decimal("18")).code == "R2"


def test_a_mile_off_the_stream_is_refused() -> None:
    with pytest.raises(ValidationError, match="not on Sanpete Creek"):
        stream().reach_at(Decimal("4"))


def test_travel_time_adds_up_the_reaches_it_crosses() -> None:
    creek = stream()
    slow = Decimal("4") * Decimal("5280") / Decimal("2")
    fast = Decimal("8") * Decimal("5280") / Decimal("4")
    assert creek.travel_seconds(Decimal("26"), Decimal("14")) == slow + fast


def test_travel_time_inside_one_reach_is_proportional() -> None:
    assert stream().travel_seconds(Decimal("30"), Decimal("29")) == Decimal("2640")


def test_carried_fraction_compounds_reach_by_reach() -> None:
    carried = stream().carried_fraction(Decimal("30"), Decimal("14"))
    assert carried == Decimal("0.92") * Decimal("0.92")


def test_water_does_not_run_upstream() -> None:
    with pytest.raises(ValidationError, match="does not run that way"):
        stream().travel_seconds(Decimal("14"), Decimal("22"))


def test_a_span_that_leaves_the_stream_is_refused() -> None:
    with pytest.raises(ValidationError, match="leave Sanpete Creek"):
        stream().travel_seconds(Decimal("34"), Decimal("22"))


def test_a_gage_point_is_just_a_place_with_a_datum() -> None:
    gage = GagePoint("SANP-1", "Below the forks", Decimal("22"), Decimal("5412.30"))
    assert gage.mile == Decimal("22")
    assert gage.datum_elevation_feet == Decimal("5412.30")
