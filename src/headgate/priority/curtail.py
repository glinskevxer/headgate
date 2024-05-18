"""Curtailment notices: the paper that follows a call.

A decision to honour a call is not itself a shut headgate. The commissioner
serves a notice, the notice takes effect after the district's notice period so
the irrigator has a chance to finish the set he is on, and it stands until it
is lifted. Everything downstream of this, from what an order may ask for to
what the season report says happened, reads the register rather than the call.

A notice is never edited. Lifting one writes a lift date on it and leaves the
rest alone, so the register can still say what the rule was on any day.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from decimal import Decimal

from ..errors import ConflictError, NotFoundError, PolicyError, ValidationError
from ..ids import DecreeNumber
from ..units import round_rate
from .call import CallDecision, CallOutcome

DEFAULT_NOTICE_HOURS = 24


@dataclass(frozen=True, slots=True)
class CurtailmentNotice:
    """One right told to cut back, and by how much."""

    decree: DecreeNumber
    called_by: DecreeNumber
    issued_at: datetime
    effective_at: datetime
    curtailed_cfs: Decimal
    allowed_cfs: Decimal
    reason: str
    lifted_at: datetime | None = None

    def __post_init__(self) -> None:
        if self.effective_at < self.issued_at:
            raise ValidationError(f"the notice on {self.decree} takes effect before it was served")
        if self.curtailed_cfs < 0 or self.allowed_cfs < 0:
            raise ValidationError(f"the notice on {self.decree} carries a negative rate")
        if self.lifted_at is not None and self.lifted_at < self.effective_at:
            raise ValidationError(f"the notice on {self.decree} was lifted before it took effect")

    def stands_at(self, moment: datetime) -> bool:
        if moment < self.effective_at:
            return False
        return self.lifted_at is None or moment < self.lifted_at

    @property
    def is_total(self) -> bool:
        return self.allowed_cfs == 0


@dataclass(frozen=True, slots=True)
class CurtailmentRegister:
    """Every notice the commissioner has served this season."""

    notices: tuple[CurtailmentNotice, ...] = ()

    def standing_at(self, moment: datetime) -> tuple[CurtailmentNotice, ...]:
        return tuple(notice for notice in self.notices if notice.stands_at(moment))

    def allowed_rate(self, decree: DecreeNumber, moment: datetime) -> Decimal | None:
        """The most restrictive rate standing against a right, if any."""

        standing = [
            notice.allowed_cfs for notice in self.standing_at(moment) if notice.decree == decree
        ]
        if not standing:
            return None
        return round_rate(min(standing))

    def is_curtailed(self, decree: DecreeNumber, moment: datetime) -> bool:
        return self.allowed_rate(decree, moment) is not None

    def issue(self, notice: CurtailmentNotice) -> CurtailmentRegister:
        for existing in self.notices:
            if (
                existing.decree == notice.decree
                and existing.called_by == notice.called_by
                and existing.stands_at(notice.effective_at)
            ):
                raise ConflictError(
                    f"a notice on {notice.decree} for the call by {notice.called_by} already stands"
                )
        return replace(self, notices=(*self.notices, notice))

    def lift(
        self, decree: DecreeNumber, called_by: DecreeNumber, at: datetime
    ) -> CurtailmentRegister:
        """Lift the standing notice on a right, leaving the record behind."""

        updated: list[CurtailmentNotice] = []
        found = False
        for notice in self.notices:
            if (
                not found
                and notice.decree == decree
                and notice.called_by == called_by
                and notice.stands_at(at)
            ):
                updated.append(replace(notice, lifted_at=at))
                found = True
            else:
                updated.append(notice)
        if not found:
            raise NotFoundError("standing notice", f"{decree} called by {called_by}")
        return replace(self, notices=tuple(updated))

    def lift_all(self, called_by: DecreeNumber, at: datetime) -> CurtailmentRegister:
        """Lift everything served for one call, which is how a call ends."""

        register = self
        for notice in self.standing_at(at):
            if notice.called_by == called_by:
                register = register.lift(notice.decree, called_by, at)
        return register


def notices_from(
    decision: CallDecision,
    issued_at: datetime,
    notice_hours: int = DEFAULT_NOTICE_HOURS,
) -> tuple[CurtailmentNotice, ...]:
    """Turn an honoured call into the notices that carry it out."""

    if decision.outcome is not CallOutcome.HONOURED:
        raise PolicyError(
            f"a call that came back {decision.outcome.value} serves no notices: {decision.reason}"
        )
    if notice_hours < 0:
        raise ValidationError("a notice period may not run backwards")
    effective = issued_at + timedelta(hours=notice_hours)
    calling = decision.call.decree_owner.decree
    return tuple(
        CurtailmentNotice(
            decree=item.right.decree,
            called_by=calling,
            issued_at=issued_at,
            effective_at=effective,
            curtailed_cfs=item.curtailed_cfs,
            allowed_cfs=round_rate(
                item.right.rate_or_zero() - item.curtailed_cfs
                if item.right.rate_or_zero() > item.curtailed_cfs
                else Decimal("0")
            ),
            reason=f"call by {calling}: {decision.reason}",
        )
        for item in decision.curtailments
    )


def serve(
    register: CurtailmentRegister,
    decision: CallDecision,
    issued_at: datetime,
    notice_hours: int = DEFAULT_NOTICE_HOURS,
) -> CurtailmentRegister:
    """Serve every notice an honoured call calls for."""

    served = register
    for notice in notices_from(decision, issued_at, notice_hours):
        served = served.issue(notice)
    return served
