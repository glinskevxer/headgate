"""Placing a call, and deciding whether the commissioner will answer it.

A call is a senior right saying it is short. Answering it means shutting
juniors until the shortage is covered, and three things decide whether that is
worth doing.

Only a junior upstream of the calling point can help. Shutting a junior below
the caller puts water in the stream where the caller will never see it, so
those are left alone however junior they are.

What arrives is less than what was shut off, because the reaches in between
take their share. The commissioner has to shut more than the shortfall and
sometimes a great deal more.

And it has to get there in time. Water that reaches the headgate after the
crop needed it answers nothing. A call that cannot be usefully answered is
futile, and the futile call doctrine says it is refused rather than half
honoured, because the juniors would be dried up for no benefit to anybody.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import Enum

from ..errors import PolicyError, ValidationError
from ..ids import DecreeNumber
from ..model.right import WaterRight, juniors_to
from ..model.stream import Stream
from ..units import round_rate, total_rate
from .travel import arrival_of, carried

FUTILE_DELIVERY_FRACTION = Decimal("0.5")


class CallOutcome(Enum):
    """What the commissioner did about it."""

    HONOURED = "honoured"
    UNNECESSARY = "unnecessary"
    FUTILE = "futile"
    REFUSED = "refused"

    @property
    def curtails_anybody(self) -> bool:
        return self is CallOutcome.HONOURED


@dataclass(frozen=True, slots=True)
class Call:
    """A senior right asking for what its decree says it gets."""

    decree_owner: WaterRight
    placed_at: datetime
    needed_by: datetime | None = None

    @property
    def diversion_mile(self) -> Decimal:
        return self.decree_owner.diversion_mile


@dataclass(frozen=True, slots=True)
class Curtailment:
    """One junior shut off, and what that is worth at the calling point."""

    right: WaterRight
    curtailed_cfs: Decimal
    delivered_cfs: Decimal
    arrives_at: datetime

    @property
    def lost_cfs(self) -> Decimal:
        return round_rate(self.curtailed_cfs - self.delivered_cfs)


@dataclass(frozen=True, slots=True)
class CallDecision:
    """What was decided, what it would take, and why."""

    call: Call
    outcome: CallOutcome
    shortfall_cfs: Decimal
    curtailments: tuple[Curtailment, ...]
    reason: str

    @property
    def curtailed_cfs(self) -> Decimal:
        return total_rate(item.curtailed_cfs for item in self.curtailments)

    @property
    def delivered_cfs(self) -> Decimal:
        return total_rate(item.delivered_cfs for item in self.curtailments)

    @property
    def remaining_shortfall_cfs(self) -> Decimal:
        remaining = self.shortfall_cfs - self.delivered_cfs
        return round_rate(remaining if remaining > 0 else Decimal("0"))

    @property
    def latest_arrival(self) -> datetime | None:
        if not self.curtailments:
            return None
        return max(item.arrives_at for item in self.curtailments)


def evaluate_call(
    stream: Stream,
    rights: list[WaterRight],
    call: Call,
    diverting: Mapping[DecreeNumber, Decimal],
    arriving_cfs: Decimal,
) -> CallDecision:
    """Decide a call against the stream as it actually stands.

    The ladder says what everybody is entitled to. This works from what is
    happening: how much is reaching the calling headgate, and how much each
    junior is diverting right now. A junior upstream keeps taking water while a
    senior below goes short, which is the whole reason a call exists.
    """

    calling = call.decree_owner
    if arriving_cfs < 0:
        raise ValidationError("a headgate cannot be receiving a negative flow")
    if not calling.can_be_called:
        return CallDecision(
            call,
            CallOutcome.REFUSED,
            Decimal("0"),
            (),
            f"decree {calling.decree} is not a decreed direct flow right",
        )
    wanted = calling.rate_or_zero()
    shortfall = round_rate(wanted - arriving_cfs) if arriving_cfs < wanted else Decimal("0")
    if shortfall <= 0:
        return CallDecision(
            call,
            CallOutcome.UNNECESSARY,
            Decimal("0"),
            (),
            f"decree {calling.decree} is getting its whole rate",
        )
    helpers = [
        right
        for right in juniors_to(rights, calling)
        if right.diversion_mile > calling.diversion_mile
        and diverting.get(right.decree, Decimal("0")) > 0
    ]
    if not helpers:
        return CallDecision(
            call,
            CallOutcome.FUTILE,
            shortfall,
            (),
            "every junior taking water is below the calling point",
        )
    curtailments: list[Curtailment] = []
    still_wanted = shortfall
    for junior in helpers:
        if still_wanted <= 0:
            break
        taking = diverting.get(junior.decree, Decimal("0"))
        fraction = stream.carried_fraction(junior.diversion_mile, calling.diversion_mile)
        wanted_at_source = still_wanted / fraction if fraction > 0 else taking
        shut = taking if taking < wanted_at_source else wanted_at_source
        delivered = carried(stream, junior.diversion_mile, calling.diversion_mile, shut)
        curtailments.append(
            Curtailment(
                right=junior,
                curtailed_cfs=round_rate(shut),
                delivered_cfs=delivered,
                arrives_at=arrival_of(
                    stream, junior.diversion_mile, calling.diversion_mile, call.placed_at
                ),
            )
        )
        still_wanted -= delivered
    delivered_total = sum((item.delivered_cfs for item in curtailments), Decimal("0"))
    if delivered_total < shortfall * FUTILE_DELIVERY_FRACTION:
        return CallDecision(
            call,
            CallOutcome.FUTILE,
            shortfall,
            tuple(curtailments),
            f"shutting every junior above the caller delivers {round_rate(delivered_total)} cfs "
            f"against a shortfall of {shortfall} cfs",
        )
    if call.needed_by is not None:
        latest = max(item.arrives_at for item in curtailments)
        if latest > call.needed_by:
            return CallDecision(
                call,
                CallOutcome.FUTILE,
                shortfall,
                tuple(curtailments),
                f"the water would arrive {latest:%Y-%m-%d %H:%M}, after it was needed",
            )
    return CallDecision(
        call,
        CallOutcome.HONOURED,
        shortfall,
        tuple(curtailments),
        f"{len(curtailments)} junior rights shut to deliver "
        f"{round_rate(delivered_total)} cfs at the calling point",
    )


def require_honoured(decision: CallDecision) -> CallDecision:
    """Insist a decision curtails somebody, for a caller that cannot go on."""

    if not decision.outcome.curtails_anybody:
        raise PolicyError(f"the call was {decision.outcome.value}: {decision.reason}")
    return decision
