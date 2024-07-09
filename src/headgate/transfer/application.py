"""An application to change a right, and what the district may approve.

Moving a point of diversion or a place of use is a change to everybody else's
water, so it runs a course: filed, published, open to protest, then approved on
terms or denied. Nothing skips a step and nothing goes backwards.

The terms are the whole point. An approval is not a yes, it is a yes to a
quantity, with the ground the water came off dried up and the return flow it
used to make still owed to the stream. Both of those are conditions the office
has to be able to check next season, so they are on the record rather than in
somebody's memory.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import date
from decimal import Decimal
from enum import Enum

from ..duty.hcu import HistoricalUse
from ..errors import PolicyError, ValidationError
from ..ids import DecreeNumber, TurnoutCode


class TransferKind(Enum):
    """What the applicant wants to change."""

    POINT_OF_DIVERSION = "point_of_diversion"
    PLACE_OF_USE = "place_of_use"
    BOTH = "both"

    @property
    def moves_the_headgate(self) -> bool:
        return self in {TransferKind.POINT_OF_DIVERSION, TransferKind.BOTH}

    @property
    def moves_the_ground(self) -> bool:
        return self in {TransferKind.PLACE_OF_USE, TransferKind.BOTH}


class TransferStatus(Enum):
    """Where the application stands."""

    FILED = "filed"
    PUBLISHED = "published"
    PROTESTED = "protested"
    APPROVED = "approved"
    DENIED = "denied"
    WITHDRAWN = "withdrawn"

    @property
    def is_final(self) -> bool:
        return self in {TransferStatus.APPROVED, TransferStatus.DENIED, TransferStatus.WITHDRAWN}


@dataclass(frozen=True, slots=True)
class TransferTerms:
    """What an approval actually allows, and what it costs the applicant."""

    approved_af: Decimal
    dry_up_parcels: tuple[str, ...]
    return_flow_af: Decimal
    conditions: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.approved_af <= 0:
            raise ValidationError("terms that approve no water are a denial")
        if self.return_flow_af < 0:
            raise ValidationError("a return flow obligation may not be negative")


@dataclass(frozen=True, slots=True)
class TransferApplication:
    """One application to change one right."""

    number: str
    decree: DecreeNumber
    kind: TransferKind
    filed_on: date
    requested_af: Decimal
    study: HistoricalUse
    from_turnout: TurnoutCode | None = None
    to_turnout: TurnoutCode | None = None
    dry_up_parcels: tuple[str, ...] = ()
    status: TransferStatus = TransferStatus.FILED
    terms: TransferTerms | None = None
    note: str = ""

    def __post_init__(self) -> None:
        if not self.number.strip():
            raise ValidationError("an application needs a number")
        if self.requested_af <= 0:
            raise ValidationError(f"application {self.number} asks to move no water")
        if self.requested_af > self.study.average_af:
            raise PolicyError(
                f"application {self.number} asks to move {self.requested_af} acre feet and the "
                f"study proves {self.study.average_af}"
            )
        if self.kind.moves_the_headgate and self.to_turnout is None:
            raise ValidationError(f"application {self.number} moves the headgate to nowhere")
        if self.kind.moves_the_ground and not self.dry_up_parcels:
            raise PolicyError(
                f"application {self.number} moves the place of use and dries up no ground"
            )
        if self.status is TransferStatus.APPROVED and self.terms is None:
            raise ValidationError(f"application {self.number} is approved on no terms")

    @property
    def unproven_af(self) -> Decimal:
        return self.study.average_af - self.requested_af

    def publish(self) -> TransferApplication:
        if self.status is not TransferStatus.FILED:
            raise PolicyError(f"application {self.number} is {self.status.value}, not filed")
        return replace(self, status=TransferStatus.PUBLISHED)

    def protest(self, note: str) -> TransferApplication:
        if self.status is not TransferStatus.PUBLISHED:
            raise PolicyError(
                f"application {self.number} is {self.status.value} and cannot be protested"
            )
        return replace(self, status=TransferStatus.PROTESTED, note=note)

    def approve(self, terms: TransferTerms) -> TransferApplication:
        if self.status not in {TransferStatus.PUBLISHED, TransferStatus.PROTESTED}:
            raise PolicyError(
                f"application {self.number} is {self.status.value} and cannot be approved yet"
            )
        if terms.approved_af > self.requested_af:
            raise PolicyError(
                f"application {self.number} asked for {self.requested_af} acre feet and the "
                f"terms grant {terms.approved_af}"
            )
        if set(terms.dry_up_parcels) != set(self.dry_up_parcels):
            raise PolicyError(
                f"application {self.number} offered to dry up "
                f"{len(self.dry_up_parcels)} parcels and the terms name "
                f"{len(terms.dry_up_parcels)}"
            )
        return replace(self, status=TransferStatus.APPROVED, terms=terms)

    def deny(self, reason: str) -> TransferApplication:
        if self.status.is_final:
            raise PolicyError(f"application {self.number} is already {self.status.value}")
        return replace(self, status=TransferStatus.DENIED, note=reason)

    def withdraw(self, reason: str) -> TransferApplication:
        if self.status.is_final:
            raise PolicyError(f"application {self.number} is already {self.status.value}")
        return replace(self, status=TransferStatus.WITHDRAWN, note=reason)


def terms_for(
    application: TransferApplication,
    approved_af: Decimal,
    consumed_share: Decimal,
    conditions: tuple[str, ...] = (),
) -> TransferTerms:
    """Build terms that carry the return flow the old farm used to make."""

    if consumed_share <= 0 or consumed_share > 1:
        raise ValidationError(f"{consumed_share} is not a share of the delivery consumed")
    delivered = approved_af / consumed_share
    return TransferTerms(
        approved_af=approved_af,
        dry_up_parcels=application.dry_up_parcels,
        return_flow_af=(delivered - approved_af).quantize(Decimal("0.0001")),
        conditions=conditions,
    )
