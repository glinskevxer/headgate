from datetime import date, datetime
from decimal import Decimal

import pytest

from headgate.errors import PolicyError, ValidationError
from headgate.ids import DecreeNumber
from headgate.model.right import Priority, RightKind, RightStatus, WaterRight
from headgate.model.stream import Reach, Stream
from headgate.priority.call import (
    Call,
    CallOutcome,
    evaluate_call,
    require_honoured,
)

NOON = datetime(2025, 7, 4, 12)


def stream(loss: str = "0.01") -> Stream:
    return Stream(
        name="Sanpete Creek",
        reaches=(
            Reach("R1", "Upper", Decimal("40"), Decimal("20"), Decimal("2"), Decimal(loss)),
            Reach("R2", "Lower", Decimal("20"), Decimal("4"), Decimal("3"), Decimal(loss)),
        ),
    )


def right(
    sequence: int,
    year: int,
    mile: str,
    rate: str | None = "4",
    kind: RightKind = RightKind.DIRECT_FLOW,
    status: RightStatus = RightStatus.DECREED,
    volume: str | None = None,
) -> WaterRight:
    return WaterRight(
        decree=DecreeNumber(f"CDA-1920-{sequence}"),
        owner=f"Owner {sequence}",
        kind=kind,
        priority=Priority(date(year, 5, 1), 1920, sequence),
        diversion_mile=Decimal(mile),
        rate_cfs=Decimal(rate) if rate is not None else None,
        volume_af=Decimal(volume) if volume is not None else None,
        status=status,
    )


SENIOR = right(1, 1873, "10", "6")
UPSTREAM_JUNIOR = right(5, 1901, "30", "5")
NEARER_JUNIOR = right(4, 1895, "22", "4")
DOWNSTREAM_JUNIOR = right(6, 1905, "6", "5")


def ladder() -> list[WaterRight]:
    return [SENIOR, UPSTREAM_JUNIOR, NEARER_JUNIOR, DOWNSTREAM_JUNIOR]


def call(right_calling: WaterRight = SENIOR, needed_by: datetime | None = None) -> Call:
    return Call(decree_owner=right_calling, placed_at=NOON, needed_by=needed_by)


def diverting(**taken: str) -> dict[DecreeNumber, Decimal]:
    return {DecreeNumber(f"CDA-1920-{seq[1:]}"): Decimal(value) for seq, value in taken.items()}


def test_a_right_getting_its_whole_rate_has_nothing_to_call_for() -> None:
    decision = evaluate_call(stream(), ladder(), call(), diverting(d5="5"), Decimal("6"))
    assert decision.outcome is CallOutcome.UNNECESSARY
    assert decision.curtailments == ()


def test_a_short_senior_right_gets_its_juniors_shut() -> None:
    decision = evaluate_call(stream(), ladder(), call(), diverting(d5="5", d4="4"), Decimal("2"))
    assert decision.outcome is CallOutcome.HONOURED
    assert decision.delivered_cfs > Decimal("0")
    assert decision.remaining_shortfall_cfs == Decimal("0")


def test_the_most_junior_upstream_right_is_shut_first() -> None:
    decision = evaluate_call(stream(), ladder(), call(), diverting(d5="5", d4="4"), Decimal("2"))
    assert decision.curtailments[0].right.decree == DecreeNumber("CDA-1920-5")


def test_a_junior_below_the_calling_point_is_left_alone() -> None:
    decision = evaluate_call(
        stream(), ladder(), call(), diverting(d5="5", d4="4", d6="5"), Decimal("2")
    )
    shut = [item.right.decree for item in decision.curtailments]
    assert DecreeNumber("CDA-1920-6") not in shut


def test_a_call_with_only_juniors_downstream_is_futile() -> None:
    rights = [SENIOR, DOWNSTREAM_JUNIOR]
    decision = evaluate_call(stream(), rights, call(), diverting(d6="5"), Decimal("2"))
    assert decision.outcome is CallOutcome.FUTILE
    assert "below the calling point" in decision.reason


def test_carriage_loss_means_more_is_shut_than_arrives() -> None:
    decision = evaluate_call(stream(), ladder(), call(), diverting(d5="5", d4="4"), Decimal("2"))
    assert decision.curtailed_cfs > decision.delivered_cfs
    assert decision.curtailments[0].lost_cfs > Decimal("0")


def test_a_call_that_cannot_deliver_half_the_shortfall_is_futile() -> None:
    hungry = stream("0.04")
    far_junior = right(7, 1910, "38", "2")
    rights = [SENIOR, far_junior]
    decision = evaluate_call(
        hungry, rights, call(), {far_junior.decree: Decimal("2")}, Decimal("2")
    )
    assert decision.outcome is CallOutcome.FUTILE
    assert "against a shortfall" in decision.reason


def test_water_that_arrives_too_late_makes_the_call_futile() -> None:
    decision = evaluate_call(
        stream(),
        ladder(),
        call(needed_by=datetime(2025, 7, 4, 12, 30)),
        diverting(d5="5", d4="4"),
        Decimal("2"),
    )
    assert decision.outcome is CallOutcome.FUTILE
    assert "after it was needed" in decision.reason


def test_water_that_arrives_in_time_is_honoured() -> None:
    decision = evaluate_call(
        stream(),
        ladder(),
        call(needed_by=datetime(2025, 7, 5, 12)),
        diverting(d5="5", d4="4"),
        Decimal("2"),
    )
    assert decision.outcome is CallOutcome.HONOURED
    assert decision.latest_arrival is not None


def test_an_abandoned_right_cannot_call() -> None:
    dead = right(2, 1870, "10", "6", status=RightStatus.ABANDONED)
    decision = evaluate_call(
        stream(), [dead, UPSTREAM_JUNIOR], call(dead), diverting(d5="5"), Decimal("0")
    )
    assert decision.outcome is CallOutcome.REFUSED
    assert "direct flow" in decision.reason


def test_a_storage_right_cannot_call_on_the_stream() -> None:
    stored = right(3, 1866, "10", None, RightKind.STORAGE, volume="1200")
    decision = evaluate_call(
        stream(), [stored, UPSTREAM_JUNIOR], call(stored), diverting(d5="5"), Decimal("0")
    )
    assert decision.outcome is CallOutcome.REFUSED


def test_only_as_many_juniors_as_are_needed_are_shut() -> None:
    decision = evaluate_call(stream(), ladder(), call(), diverting(d5="5", d4="4"), Decimal("5"))
    assert len(decision.curtailments) == 1


def test_a_futile_call_curtails_nobody_even_though_it_lists_what_it_would_take() -> None:
    decision = evaluate_call(
        stream(),
        ladder(),
        call(needed_by=datetime(2025, 7, 4, 12, 30)),
        diverting(d5="5", d4="4"),
        Decimal("2"),
    )
    assert not decision.outcome.curtails_anybody
    assert decision.curtailments != ()


def test_a_negative_arriving_flow_is_refused() -> None:
    with pytest.raises(ValidationError, match="negative flow"):
        evaluate_call(stream(), ladder(), call(), diverting(d5="5"), Decimal("-1"))


def test_a_caller_that_cannot_go_on_insists_on_an_answer() -> None:
    decision = evaluate_call(stream(), ladder(), call(), diverting(d5="5", d4="4"), Decimal("2"))
    assert require_honoured(decision) is decision
    futile = evaluate_call(
        stream(), [SENIOR, DOWNSTREAM_JUNIOR], call(), diverting(d6="5"), Decimal("2")
    )
    with pytest.raises(PolicyError, match="the call was futile"):
        require_honoured(futile)
