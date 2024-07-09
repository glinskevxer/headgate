from datetime import date
from decimal import Decimal

import pytest

from headgate.duty.hcu import HistoricalUse, YearFinding
from headgate.errors import PolicyError, ValidationError
from headgate.ids import DecreeNumber, TurnoutCode
from headgate.transfer.application import (
    TransferApplication,
    TransferKind,
    TransferStatus,
    TransferTerms,
    terms_for,
)


def study(average: str = "120") -> HistoricalUse:
    return HistoricalUse(
        findings=(YearFinding(2020, Decimal(average), True, "measured and representative"),),
        average_af=Decimal(average),
    )


def application(**overrides: object) -> TransferApplication:
    fields: dict[str, object] = {
        "number": "T-2025-04",
        "decree": DecreeNumber("CDA-1889-4"),
        "kind": TransferKind.BOTH,
        "filed_on": date(2025, 2, 10),
        "requested_af": Decimal("60"),
        "study": study(),
        "from_turnout": TurnoutCode("L2-14"),
        "to_turnout": TurnoutCode("L2-20"),
        "dry_up_parcels": ("11-042-001",),
    }
    fields.update(overrides)
    return TransferApplication(**fields)  # type: ignore[arg-type]


def test_an_application_needs_a_number_and_some_water() -> None:
    with pytest.raises(ValidationError, match="needs a number"):
        application(number="  ")
    with pytest.raises(ValidationError, match="no water"):
        application(requested_af=Decimal("0"))


def test_nothing_may_be_moved_that_the_study_does_not_prove() -> None:
    with pytest.raises(PolicyError, match="the study proves"):
        application(requested_af=Decimal("200"))


def test_moving_the_headgate_needs_somewhere_to_move_it_to() -> None:
    with pytest.raises(ValidationError, match="headgate to nowhere"):
        application(kind=TransferKind.POINT_OF_DIVERSION, to_turnout=None)


def test_moving_the_place_of_use_dries_up_ground() -> None:
    with pytest.raises(PolicyError, match="dries up no ground"):
        application(kind=TransferKind.PLACE_OF_USE, dry_up_parcels=())


def test_a_point_of_diversion_change_does_not_dry_anything_up() -> None:
    moved = application(kind=TransferKind.POINT_OF_DIVERSION, dry_up_parcels=())
    assert moved.kind.moves_the_headgate
    assert not moved.kind.moves_the_ground


def test_the_unproven_remainder_is_reported() -> None:
    assert application().unproven_af == Decimal("60")


def test_an_application_runs_filed_then_published_then_approved() -> None:
    filed = application()
    published = filed.publish()
    assert published.status is TransferStatus.PUBLISHED
    approved = published.approve(terms_for(published, Decimal("60"), Decimal("0.5")))
    assert approved.status is TransferStatus.APPROVED
    assert approved.terms is not None


def test_an_application_cannot_be_published_twice() -> None:
    published = application().publish()
    with pytest.raises(PolicyError, match="not filed"):
        published.publish()


def test_a_protest_can_still_be_approved() -> None:
    protested = application().publish().protest("the ditch below will go dry")
    assert protested.status is TransferStatus.PROTESTED
    approved = protested.approve(terms_for(protested, Decimal("40"), Decimal("0.5")))
    assert approved.status is TransferStatus.APPROVED


def test_an_unpublished_application_cannot_be_protested() -> None:
    with pytest.raises(PolicyError, match="cannot be protested"):
        application().protest("too early")


def test_an_unpublished_application_cannot_be_approved() -> None:
    filed = application()
    with pytest.raises(PolicyError, match="cannot be approved yet"):
        filed.approve(terms_for(filed, Decimal("60"), Decimal("0.5")))


def test_the_terms_may_not_grant_more_than_was_asked_for() -> None:
    published = application()
    with pytest.raises(PolicyError, match="the terms grant"):
        published.publish().approve(TransferTerms(Decimal("80"), ("11-042-001",), Decimal("10")))


def test_the_terms_have_to_name_the_ground_that_was_offered() -> None:
    published = application().publish()
    with pytest.raises(PolicyError, match="offered to dry up"):
        published.approve(TransferTerms(Decimal("60"), (), Decimal("10")))


def test_terms_that_approve_nothing_are_a_denial() -> None:
    with pytest.raises(ValidationError, match="are a denial"):
        TransferTerms(Decimal("0"), (), Decimal("0"))


def test_a_negative_return_flow_obligation_is_refused() -> None:
    with pytest.raises(ValidationError, match="may not be negative"):
        TransferTerms(Decimal("60"), (), Decimal("-1"))


def test_an_application_can_be_denied_or_withdrawn_at_any_stage() -> None:
    assert application().deny("no water to move").status is TransferStatus.DENIED
    assert application().withdraw("sold the farm").status is TransferStatus.WITHDRAWN


def test_a_final_application_stays_final() -> None:
    denied = application().deny("no water to move")
    with pytest.raises(PolicyError, match="already denied"):
        denied.withdraw("changed my mind")


def test_the_return_flow_falls_out_of_the_consumed_share() -> None:
    terms = terms_for(application(), Decimal("60"), Decimal("0.5"))
    assert terms.return_flow_af == Decimal("60.0000")


def test_a_more_efficient_farm_owes_less_return_flow() -> None:
    thirsty = terms_for(application(), Decimal("60"), Decimal("0.4"))
    efficient = terms_for(application(), Decimal("60"), Decimal("0.8"))
    assert efficient.return_flow_af < thirsty.return_flow_af


def test_an_impossible_consumed_share_is_refused() -> None:
    with pytest.raises(ValidationError, match="not a share"):
        terms_for(application(), Decimal("60"), Decimal("1.4"))


def test_an_approved_application_carries_its_terms_on_the_record() -> None:
    with pytest.raises(ValidationError, match="approved on no terms"):
        application(status=TransferStatus.APPROVED)
