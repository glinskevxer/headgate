from datetime import date
from decimal import Decimal

import pytest

from headgate.errors import ValidationError
from headgate.ids import DecreeNumber
from headgate.model.right import Priority, RightKind, RightStatus, WaterRight
from headgate.priority.ladder import distribute, shortfall_of, supply_to_satisfy


def right(
    sequence: int,
    year: int,
    rate: str | None = "4",
    kind: RightKind = RightKind.DIRECT_FLOW,
    volume: str | None = None,
    status: RightStatus = RightStatus.DECREED,
) -> WaterRight:
    return WaterRight(
        decree=DecreeNumber(f"CDA-1889-{sequence}"),
        owner="Sanpete Ditch Company",
        kind=kind,
        priority=Priority(date(year, 5, 1), 1889, sequence),
        diversion_mile=Decimal("28.4"),
        rate_cfs=Decimal(rate) if rate is not None else None,
        volume_af=Decimal(volume) if volume is not None else None,
        status=status,
    )


def ladder() -> list[WaterRight]:
    return [right(1, 1873, "4"), right(2, 1882, "6"), right(3, 1889, "5")]


def test_plenty_of_water_leaves_everybody_whole() -> None:
    result = distribute(ladder(), Decimal("20"))
    assert not result.is_short
    assert result.unallocated_cfs == Decimal("5")


def test_a_short_stream_cuts_from_the_bottom() -> None:
    result = distribute(ladder(), Decimal("12"))
    assert result.for_decree(DecreeNumber("CDA-1889-1")).is_whole
    assert result.for_decree(DecreeNumber("CDA-1889-2")).is_whole
    assert result.for_decree(DecreeNumber("CDA-1889-3")).allocated_cfs == Decimal("2")


def test_the_right_that_runs_out_takes_what_is_left() -> None:
    result = distribute(ladder(), Decimal("7"))
    shorted = result.first_shorted
    assert shorted is not None
    assert shorted.right.decree == DecreeNumber("CDA-1889-2")
    assert shorted.allocated_cfs == Decimal("3")
    assert shorted.shorted_cfs == Decimal("3")


def test_everything_below_the_short_right_is_dry() -> None:
    result = distribute(ladder(), Decimal("7"))
    dry = [item.right.decree.sequence for item in result.dry_rights]
    assert dry == [3]


def test_an_empty_stream_leaves_everybody_dry() -> None:
    result = distribute(ladder(), Decimal("0"))
    assert len(result.dry_rights) == 3
    assert result.total_allocated_cfs == Decimal("0")


def test_a_negative_supply_is_refused() -> None:
    with pytest.raises(ValidationError, match="negative supply"):
        distribute(ladder(), Decimal("-1"))


def test_an_abandoned_right_is_not_administered() -> None:
    rights = [*ladder(), right(9, 1870, "10", status=RightStatus.ABANDONED)]
    result = distribute(rights, Decimal("15"))
    assert len(result.allocations) == 3
    assert not result.is_short


def test_storage_fills_after_every_direct_flow_right() -> None:
    rights = [*ladder(), right(4, 1866, None, RightKind.STORAGE, "1200")]
    result = distribute(rights, Decimal("15"))
    assert result.allocations[-1].right.kind is RightKind.STORAGE
    assert result.for_decree(DecreeNumber("CDA-1889-3")).is_whole


def test_storage_can_be_left_out_altogether() -> None:
    rights = [*ladder(), right(4, 1866, None, RightKind.STORAGE, "1200")]
    result = distribute(rights, Decimal("15"), fill_storage=False)
    assert len(result.allocations) == 3


def test_a_storage_right_with_no_rate_takes_nothing_from_the_stream() -> None:
    rights = [right(4, 1866, None, RightKind.STORAGE, "1200")]
    result = distribute(rights, Decimal("5"))
    assert result.total_allocated_cfs == Decimal("0")


def test_a_decree_that_was_not_administered_cannot_be_looked_up() -> None:
    result = distribute(ladder(), Decimal("15"))
    with pytest.raises(ValidationError, match="not in this distribution"):
        result.for_decree(DecreeNumber("CDA-1889-9"))


def test_the_supply_a_right_needs_is_everything_above_it() -> None:
    assert supply_to_satisfy(ladder(), DecreeNumber("CDA-1889-1")) == Decimal("4")
    assert supply_to_satisfy(ladder(), DecreeNumber("CDA-1889-3")) == Decimal("15")


def test_asking_for_a_right_off_the_ladder_is_refused() -> None:
    with pytest.raises(ValidationError, match="not on this ladder"):
        supply_to_satisfy(ladder(), DecreeNumber("CDA-1889-9"))


def test_the_shortfall_is_what_a_call_would_ask_for() -> None:
    result = distribute(ladder(), Decimal("12"))
    assert shortfall_of(result, DecreeNumber("CDA-1889-3")) == Decimal("3")
    assert shortfall_of(result, DecreeNumber("CDA-1889-1")) == Decimal("0")
