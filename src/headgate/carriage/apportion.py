"""Charging the season's ditch loss out to the turnouts that were running.

The headgate is measured and every turnout is measured, and the difference is
the loss. Somebody has to carry it, and which somebody depends on a rule the
board adopts rather than on any hydrology.

By delivery spreads it in proportion to what each turnout took, which is simple
and charges the man at the head of the ditch for water he never saw run past
him. By share spreads it on the stock book, which the shareholders at the far
end prefer and which ignores whether they irrigated at all. By leg charges each
turnout the loss on the reaches it actually used, which is the fairest and the
one that needs the whole ditch geometry to compute.

The pieces always add back to the measured loss. A rounding remainder goes to
the largest charge, because a tenth of an acre foot has to land somewhere and
that is the one place nobody will notice it.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal
from enum import Enum

from ..errors import PolicyError, ValidationError
from ..ids import TurnoutCode
from ..model.ditch import DitchSystem
from ..units import round_volume, total_volume
from .loss import carriage_for, carried_fraction


class LossPolicy(Enum):
    """How the board decided the ditch loss gets charged out."""

    BY_DELIVERY = "by_delivery"
    BY_SHARE = "by_share"
    BY_LEG = "by_leg"

    @property
    def needs_shares(self) -> bool:
        return self is LossPolicy.BY_SHARE

    @property
    def needs_the_ditch(self) -> bool:
        return self is LossPolicy.BY_LEG


@dataclass(frozen=True, slots=True)
class Charge:
    """One turnout's share of the loss."""

    turnout: TurnoutCode
    delivered_af: Decimal
    loss_af: Decimal

    @property
    def diverted_af(self) -> Decimal:
        return round_volume(self.delivered_af + self.loss_af)


@dataclass(frozen=True, slots=True)
class Apportionment:
    """The whole charge out, and the rule it was made under."""

    policy: LossPolicy
    charges: tuple[Charge, ...]

    @property
    def total_loss_af(self) -> Decimal:
        return total_volume(item.loss_af for item in self.charges)

    @property
    def total_delivered_af(self) -> Decimal:
        return total_volume(item.delivered_af for item in self.charges)

    def for_turnout(self, turnout: TurnoutCode) -> Charge:
        for item in self.charges:
            if item.turnout == turnout:
                return item
        raise PolicyError(f"turnout {turnout} was not in this apportionment")


def _weights_by_leg(
    system: DitchSystem, delivered: Mapping[TurnoutCode, Decimal]
) -> dict[TurnoutCode, Decimal]:
    weights: dict[TurnoutCode, Decimal] = {}
    for turnout, volume in delivered.items():
        fraction = carried_fraction(system, turnout)
        weights[turnout] = round_volume(volume / fraction - volume)
    return weights


def _spread(
    total: Decimal, weights: Mapping[TurnoutCode, Decimal], order: list[TurnoutCode]
) -> dict[TurnoutCode, Decimal]:
    weight_total = sum(weights.values(), Decimal("0"))
    if weight_total <= 0:
        raise PolicyError("nothing to charge the loss against")
    pieces = {turnout: round_volume(total * weights[turnout] / weight_total) for turnout in order}
    residue = round_volume(total - sum(pieces.values(), Decimal("0")))
    if residue != 0:
        largest = max(order, key=lambda code: (pieces[code], str(code)))
        pieces[largest] = round_volume(pieces[largest] + residue)
    return pieces


def apportion(
    delivered: Mapping[TurnoutCode, Decimal],
    loss_af: Decimal,
    policy: LossPolicy,
    system: DitchSystem | None = None,
    shares: Mapping[TurnoutCode, Decimal] | None = None,
) -> Apportionment:
    """Charge a measured loss out under the district's rule."""

    if loss_af < 0:
        raise ValidationError("a ditch that gained water is not a loss to charge out")
    if not delivered:
        raise PolicyError("no turnout ran, so there is nobody to charge the loss to")
    if policy.needs_shares and shares is None:
        raise PolicyError("charging by share needs the shares held at each turnout")
    if policy.needs_the_ditch and system is None:
        raise PolicyError("charging by leg needs the ditch the water ran down")
    order = sorted(delivered, key=str)
    if policy is LossPolicy.BY_DELIVERY:
        weights = {turnout: delivered[turnout] for turnout in order}
    elif policy is LossPolicy.BY_SHARE:
        assert shares is not None
        missing = [turnout for turnout in order if turnout not in shares]
        if missing:
            raise PolicyError(f"no shares are recorded at {missing[0]}")
        weights = {turnout: shares[turnout] for turnout in order}
    else:
        assert system is not None
        weights = _weights_by_leg(system, delivered)
    pieces = _spread(loss_af, weights, order)
    return Apportionment(
        policy=policy,
        charges=tuple(
            Charge(turnout=turnout, delivered_af=delivered[turnout], loss_af=pieces[turnout])
            for turnout in order
        ),
    )


def measured_loss(headgate_af: Decimal, delivered: Mapping[TurnoutCode, Decimal]) -> Decimal:
    """What the headgate passed less what the turnouts took."""

    taken = sum(delivered.values(), Decimal("0"))
    if taken > headgate_af:
        raise PolicyError(
            f"the turnouts took {round_volume(taken)} acre feet and the headgate passed "
            f"{round_volume(headgate_af)}, which is not possible"
        )
    return round_volume(headgate_af - taken)


def expected_loss(system: DitchSystem, delivered: Mapping[TurnoutCode, Decimal]) -> Decimal:
    """What the ditch should have lost carrying those deliveries."""

    total = Decimal("0")
    for turnout, volume in delivered.items():
        fraction = carried_fraction(system, turnout)
        total += volume / fraction - volume
    return round_volume(total)


def unexplained_loss(
    system: DitchSystem, headgate_af: Decimal, delivered: Mapping[TurnoutCode, Decimal]
) -> Decimal:
    """What the ditch lost beyond what the loss rates account for.

    A big number here is a break in the bank, a gate somebody left open, or a
    turnout nobody is measuring. It is the one figure on the season report the
    board actually reads.
    """

    return round_volume(measured_loss(headgate_af, delivered) - expected_loss(system, delivered))


def carriage_summary(system: DitchSystem, turnout: TurnoutCode, headgate_cfs: Decimal) -> str:
    """One line for the report, naming every ditch the water ran down."""

    carriage = carriage_for(system, turnout, headgate_cfs)
    legs = ", ".join(f"{leg.ditch.code} {leg.miles:.2f} mi" for leg in carriage.legs)
    return (
        f"{turnout}: {carriage.headgate_cfs} cfs in, {carriage.delivered_cfs} cfs out over {legs}"
    )
