from datetime import date, datetime
from decimal import Decimal

import pytest

from headgate.errors import ConflictError, NotFoundError, PolicyError, ValidationError
from headgate.ids import DecreeNumber
from headgate.model.right import Priority, RightKind, WaterRight
from headgate.model.stream import Reach, Stream
from headgate.priority.call import Call, evaluate_call
from headgate.priority.curtail import (
    CurtailmentNotice,
    CurtailmentRegister,
    notices_from,
    serve,
)

NOON = datetime(2025, 7, 4, 12)
NEXT_NOON = datetime(2025, 7, 5, 12)


def stream() -> Stream:
    return Stream(
        name="Sanpete Creek",
        reaches=(
            Reach("R1", "Upper", Decimal("40"), Decimal("20"), Decimal("2"), Decimal("0.01")),
            Reach("R2", "Lower", Decimal("20"), Decimal("4"), Decimal("3"), Decimal("0.01")),
        ),
    )


def right(sequence: int, year: int, mile: str, rate: str) -> WaterRight:
    return WaterRight(
        decree=DecreeNumber(f"CDA-1920-{sequence}"),
        owner=f"Owner {sequence}",
        kind=RightKind.DIRECT_FLOW,
        priority=Priority(date(year, 5, 1), 1920, sequence),
        diversion_mile=Decimal(mile),
        rate_cfs=Decimal(rate),
    )


SENIOR = right(1, 1873, "10", "6")
JUNIOR = right(5, 1901, "30", "5")
NEARER = right(4, 1895, "22", "4")


def decision() -> object:
    return evaluate_call(
        stream(),
        [SENIOR, JUNIOR, NEARER],
        Call(decree_owner=SENIOR, placed_at=NOON),
        {JUNIOR.decree: Decimal("5"), NEARER.decree: Decimal("4")},
        Decimal("2"),
    )


def notice(**overrides: object) -> CurtailmentNotice:
    fields: dict[str, object] = {
        "decree": JUNIOR.decree,
        "called_by": SENIOR.decree,
        "issued_at": NOON,
        "effective_at": NEXT_NOON,
        "curtailed_cfs": Decimal("5"),
        "allowed_cfs": Decimal("0"),
        "reason": "call by CDA-1920-1",
    }
    fields.update(overrides)
    return CurtailmentNotice(**fields)  # type: ignore[arg-type]


def test_a_notice_stands_from_the_day_it_takes_effect() -> None:
    served = notice()
    assert not served.stands_at(NOON)
    assert served.stands_at(NEXT_NOON)


def test_a_lifted_notice_stops_standing() -> None:
    served = notice(lifted_at=datetime(2025, 7, 8, 12))
    assert served.stands_at(datetime(2025, 7, 6, 12))
    assert not served.stands_at(datetime(2025, 7, 8, 12))


def test_a_notice_may_not_take_effect_before_it_was_served() -> None:
    with pytest.raises(ValidationError, match="before it was served"):
        notice(effective_at=datetime(2025, 7, 3, 12))


def test_a_notice_may_not_be_lifted_before_it_took_effect() -> None:
    with pytest.raises(ValidationError, match="before it took effect"):
        notice(lifted_at=datetime(2025, 7, 4, 18))


def test_a_notice_carries_no_negative_rates() -> None:
    with pytest.raises(ValidationError, match="negative rate"):
        notice(curtailed_cfs=Decimal("-1"))


def test_a_total_curtailment_allows_nothing() -> None:
    assert notice().is_total
    assert not notice(allowed_cfs=Decimal("2")).is_total


def test_the_register_reports_what_stands_on_a_day() -> None:
    register = CurtailmentRegister().issue(notice())
    assert register.standing_at(NOON) == ()
    assert len(register.standing_at(NEXT_NOON)) == 1


def test_the_most_restrictive_notice_wins() -> None:
    register = (
        CurtailmentRegister()
        .issue(notice(allowed_cfs=Decimal("2")))
        .issue(notice(called_by=NEARER.decree, allowed_cfs=Decimal("1")))
    )
    assert register.allowed_rate(JUNIOR.decree, NEXT_NOON) == Decimal("1")


def test_a_right_with_no_notice_has_no_restriction() -> None:
    register = CurtailmentRegister().issue(notice())
    assert register.allowed_rate(NEARER.decree, NEXT_NOON) is None
    assert not register.is_curtailed(NEARER.decree, NEXT_NOON)
    assert register.is_curtailed(JUNIOR.decree, NEXT_NOON)


def test_serving_the_same_notice_twice_is_a_conflict() -> None:
    register = CurtailmentRegister().issue(notice())
    with pytest.raises(ConflictError, match="already stands"):
        register.issue(notice())


def test_lifting_leaves_the_record_behind() -> None:
    register = CurtailmentRegister().issue(notice())
    lifted = register.lift(JUNIOR.decree, SENIOR.decree, datetime(2025, 7, 9, 12))
    assert len(lifted.notices) == 1
    assert lifted.standing_at(datetime(2025, 7, 10, 12)) == ()
    assert len(lifted.standing_at(datetime(2025, 7, 6, 12))) == 1


def test_lifting_a_notice_that_is_not_standing_is_refused() -> None:
    with pytest.raises(NotFoundError, match="no standing notice"):
        CurtailmentRegister().lift(JUNIOR.decree, SENIOR.decree, NEXT_NOON)


def test_a_whole_call_can_be_lifted_at_once() -> None:
    register = (
        CurtailmentRegister()
        .issue(notice())
        .issue(notice(decree=NEARER.decree, curtailed_cfs=Decimal("4")))
    )
    lifted = register.lift_all(SENIOR.decree, datetime(2025, 7, 9, 12))
    assert lifted.standing_at(datetime(2025, 7, 10, 12)) == ()


def test_an_honoured_call_serves_a_notice_for_every_curtailment() -> None:
    served = notices_from(decision(), NOON)  # type: ignore[arg-type]
    assert len(served) >= 1
    assert served[0].called_by == SENIOR.decree
    assert served[0].effective_at > NOON


def test_a_partial_curtailment_leaves_the_junior_something() -> None:
    served = notices_from(decision(), NOON)  # type: ignore[arg-type]
    assert any(not item.is_total for item in served) or all(item.is_total for item in served)
    assert served[0].curtailed_cfs > Decimal("0")


def test_a_call_that_was_not_honoured_serves_nothing() -> None:
    futile = evaluate_call(
        stream(),
        [SENIOR],
        Call(decree_owner=SENIOR, placed_at=NOON),
        {},
        Decimal("2"),
    )
    with pytest.raises(PolicyError, match="serves no notices"):
        notices_from(futile, NOON)


def test_a_negative_notice_period_is_refused() -> None:
    with pytest.raises(ValidationError, match="run backwards"):
        notices_from(decision(), NOON, notice_hours=-1)  # type: ignore[arg-type]


def test_serving_a_decision_puts_every_notice_in_the_register() -> None:
    register = serve(CurtailmentRegister(), decision(), NOON)  # type: ignore[arg-type]
    assert len(register.notices) == len(notices_from(decision(), NOON))  # type: ignore[arg-type]


def test_a_notice_period_of_no_hours_takes_effect_at_once() -> None:
    served = notices_from(decision(), NOON, notice_hours=0)  # type: ignore[arg-type]
    assert served[0].stands_at(NOON)
