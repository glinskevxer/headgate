"""Cutting the answered orders down to the water that actually showed up.

An order is answered days before it runs, against the creek as it was then. On
the morning it runs the ditch has what it has, and if that is less than the
orders add up to, somebody has to be cut.

Three rules are in use. Pro rata cuts everybody by the same fraction. By share
cuts against the stock book, so a big shareholder keeps more of his order. First
ordered fills them in the order they came in and cuts the tail, which the office
likes because it is easy to explain on the telephone.

All three then run into the same wall. Below a minimum head an irrigator cannot
get water across the field at all, so a set cut under it is worse than useless.
Those are dropped and their water goes back into the pot for everybody else,
and dropping them can push another order under the minimum, so it is worked
until it settles.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal
from enum import Enum

from ..errors import PolicyError, ValidationError
from ..ids import TurnoutCode
from ..model.order import WaterOrder
from ..units import round_rate

DEFAULT_MINIMUM_HEAD_CFS = Decimal("0.5")


class ShortagePolicy(Enum):
    """How the office cuts a day that came up short."""

    PRO_RATA = "pro_rata"
    BY_SHARE = "by_share"
    FIRST_ORDERED = "first_ordered"

    @property
    def needs_shares(self) -> bool:
        return self is ShortagePolicy.BY_SHARE


@dataclass(frozen=True, slots=True)
class Cut:
    """One order, and what it is actually going to run."""

    order_id: int
    turnout: TurnoutCode
    answered_cfs: Decimal
    running_cfs: Decimal
    dropped: bool
    reason: str

    @property
    def cut_cfs(self) -> Decimal:
        return round_rate(self.answered_cfs - self.running_cfs)


@dataclass(frozen=True, slots=True)
class DayAllocation:
    """Every order on the ditch for one day, after the cut."""

    policy: ShortagePolicy
    supply_cfs: Decimal
    cuts: tuple[Cut, ...]

    @property
    def running_cfs(self) -> Decimal:
        return round_rate(sum((item.running_cfs for item in self.cuts), Decimal("0")))

    @property
    def answered_cfs(self) -> Decimal:
        return round_rate(sum((item.answered_cfs for item in self.cuts), Decimal("0")))

    @property
    def is_short(self) -> bool:
        return self.running_cfs < self.answered_cfs

    @property
    def dropped(self) -> tuple[Cut, ...]:
        return tuple(item for item in self.cuts if item.dropped)

    def for_order(self, order_id: int) -> Cut:
        for item in self.cuts:
            if item.order_id == order_id:
                return item
        raise PolicyError(f"order {order_id} was not in this allocation")


def _weights(
    orders: list[WaterOrder],
    policy: ShortagePolicy,
    shares: Mapping[TurnoutCode, Decimal] | None,
) -> dict[int, Decimal]:
    if policy is ShortagePolicy.PRO_RATA:
        return {order.order_id: order.running_cfs for order in orders}
    if policy is ShortagePolicy.BY_SHARE:
        assert shares is not None
        weights: dict[int, Decimal] = {}
        for order in orders:
            if order.turnout not in shares:
                raise PolicyError(f"no shares are recorded at {order.turnout}")
            weights[order.order_id] = shares[order.turnout]
        return weights
    return {order.order_id: order.running_cfs for order in orders}


def _first_ordered(orders: list[WaterOrder], supply_cfs: Decimal) -> dict[int, Decimal]:
    running: dict[int, Decimal] = {}
    left = supply_cfs
    for order in sorted(orders, key=lambda item: (item.placed_at, item.order_id)):
        take = order.running_cfs if order.running_cfs <= left else left
        running[order.order_id] = round_rate(take)
        left -= take
    return running


def allocate(
    orders: list[WaterOrder],
    supply_cfs: Decimal,
    policy: ShortagePolicy = ShortagePolicy.PRO_RATA,
    shares: Mapping[TurnoutCode, Decimal] | None = None,
    minimum_head_cfs: Decimal = DEFAULT_MINIMUM_HEAD_CFS,
) -> DayAllocation:
    """Work out what each answered order runs against the day's supply."""

    if supply_cfs < 0:
        raise ValidationError("the ditch cannot carry a negative supply")
    running_orders = [order for order in orders if order.status.will_run]
    if not running_orders:
        raise PolicyError("no answered order is due to run")
    if policy.needs_shares and shares is None:
        raise PolicyError("cutting by share needs the shares at each turnout")
    live = list(running_orders)
    dropped: dict[int, str] = {}
    running: dict[int, Decimal] = {}
    while True:
        wanted = sum((order.running_cfs for order in live), Decimal("0"))
        if not live:
            break
        if wanted <= supply_cfs:
            running = {order.order_id: order.running_cfs for order in live}
            break
        if policy is ShortagePolicy.FIRST_ORDERED:
            running = _first_ordered(live, supply_cfs)
        else:
            weights = _weights(live, policy, shares)
            weight_total = sum(weights.values(), Decimal("0"))
            if weight_total <= 0:
                raise PolicyError("there is nothing to cut against")
            running = {
                order.order_id: round_rate(
                    min(order.running_cfs, supply_cfs * weights[order.order_id] / weight_total)
                )
                for order in live
            }
        under = [
            order
            for order in live
            if running[order.order_id] < minimum_head_cfs
            and running[order.order_id] < order.running_cfs
        ]
        if not under:
            break
        smallest = min(under, key=lambda order: (running[order.order_id], order.order_id))
        dropped[smallest.order_id] = (
            f"cut to {running[smallest.order_id]} cfs, under the {minimum_head_cfs} cfs "
            "minimum head"
        )
        live = [order for order in live if order.order_id != smallest.order_id]
    cuts: list[Cut] = []
    for order in running_orders:
        if order.order_id in dropped:
            cuts.append(
                Cut(
                    order_id=order.order_id,
                    turnout=order.turnout,
                    answered_cfs=order.running_cfs,
                    running_cfs=Decimal("0"),
                    dropped=True,
                    reason=dropped[order.order_id],
                )
            )
            continue
        allowed = running.get(order.order_id, Decimal("0"))
        cuts.append(
            Cut(
                order_id=order.order_id,
                turnout=order.turnout,
                answered_cfs=order.running_cfs,
                running_cfs=allowed,
                dropped=False,
                reason="as answered"
                if allowed >= order.running_cfs
                else f"cut under {policy.value}",
            )
        )
    return DayAllocation(policy=policy, supply_cfs=round_rate(supply_cfs), cuts=tuple(cuts))
