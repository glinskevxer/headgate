from datetime import date
from decimal import Decimal

import pytest

from headgate.errors import ValidationError
from headgate.ids import DecreeNumber, DitchCode
from headgate.model.right import (
    Priority,
    RightKind,
    RightStatus,
    WaterRight,
    juniors_to,
    order_by_priority,
)


def priority(
    year: int, month: int = 5, day: int = 1, seq: int = 1, adjudication: int = 1889
) -> Priority:
    return Priority(date(year, month, day), adjudication, seq)


def right(
    number: str,
    year: int,
    seq: int = 1,
    kind: RightKind = RightKind.DIRECT_FLOW,
    rate: str | None = "4.5",
    volume: str | None = None,
    status: RightStatus = RightStatus.DECREED,
) -> WaterRight:
    return WaterRight(
        decree=DecreeNumber(number),
        owner="Sanpete Ditch Company",
        kind=kind,
        priority=priority(year, seq=seq),
        diversion_mile=Decimal("28.4"),
        rate_cfs=Decimal(rate) if rate is not None else None,
        volume_af=Decimal(volume) if volume is not None else None,
        ditch=DitchCode("MAIN"),
        status=status,
    )


def test_the_older_appropriation_is_senior() -> None:
    assert priority(1873).is_senior_to(priority(1889))
    assert not priority(1889).is_senior_to(priority(1873))


def test_a_tie_on_the_day_falls_to_the_sequence() -> None:
    assert priority(1889, seq=3).is_senior_to(priority(1889, seq=7))


def test_a_priority_needs_a_place_in_the_book() -> None:
    with pytest.raises(ValidationError, match="not a place in the decree book"):
        priority(1889, seq=0)


def test_an_adjudication_cannot_predate_the_appropriation() -> None:
    with pytest.raises(ValidationError, match="cannot confirm"):
        Priority(date(1902, 5, 1), 1889, 1)


def test_a_priority_describes_itself_the_way_the_book_does() -> None:
    assert priority(1873, 6, 12, 4).describe() == "1873-06-12 no 4"


def test_a_direct_flow_right_needs_a_rate() -> None:
    with pytest.raises(ValidationError, match="decrees no rate"):
        right("CDA-1889-1", 1889, rate=None)


def test_a_storage_right_needs_a_volume() -> None:
    with pytest.raises(ValidationError, match="decrees no volume"):
        right("CDA-1889-1", 1889, kind=RightKind.STORAGE, rate=None)


def test_a_storage_right_is_happy_with_only_a_volume() -> None:
    stored = right("CDA-1889-4", 1889, kind=RightKind.STORAGE, rate=None, volume="1200")
    assert stored.volume_af == Decimal("1200")
    assert stored.rate_or_zero() == Decimal("0")


def test_a_decree_number_and_its_priority_must_agree_on_the_adjudication() -> None:
    with pytest.raises(ValidationError, match="is numbered for"):
        WaterRight(
            decree=DecreeNumber("CDA-1902-3"),
            owner="Nobody",
            kind=RightKind.DIRECT_FLOW,
            priority=priority(1889),
            diversion_mile=Decimal("20"),
            rate_cfs=Decimal("1"),
        )


def test_a_zero_rate_is_refused_even_on_a_storage_right() -> None:
    with pytest.raises(ValidationError, match="decrees a rate"):
        right("CDA-1889-5", 1889, kind=RightKind.STORAGE, rate="0", volume="100")


def test_a_zero_volume_is_refused_on_a_direct_flow_right() -> None:
    with pytest.raises(ValidationError, match="decrees a volume"):
        right("CDA-1889-6", 1889, volume="0")


def test_only_a_decreed_direct_flow_right_can_call() -> None:
    assert right("CDA-1889-1", 1873).can_be_called
    assert not right("CDA-1889-2", 1873, status=RightStatus.ABANDONED).can_be_called
    stored = right("CDA-1889-3", 1873, kind=RightKind.STORAGE, rate=None, volume="500")
    assert not stored.can_be_called


def test_rights_sort_most_senior_first() -> None:
    ladder = order_by_priority(
        [right("CDA-1889-9", 1889), right("CDA-1889-1", 1873), right("CDA-1889-4", 1882)]
    )
    assert [item.decree.sequence for item in ladder] == [1, 4, 9]


def test_juniors_come_back_most_junior_first() -> None:
    rights = [right("CDA-1889-9", 1889), right("CDA-1889-1", 1873), right("CDA-1889-4", 1882)]
    calling = right("CDA-1889-1", 1873)
    assert [item.decree.sequence for item in juniors_to(rights, calling)] == [9, 4]


def test_a_right_is_not_junior_to_itself() -> None:
    rights = [right("CDA-1889-1", 1873)]
    assert juniors_to(rights, rights[0]) == []
