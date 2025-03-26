"""Answering an order.

Six things can cut an order down and they are checked in the order that gives
the clearest answer. An account that is not in good standing gets a refusal
rather than a reduction. Everything after that reduces: the shares behind the
turnout, the turnout itself, whatever is left of the lateral once the orders
already answered are counted, any curtailment standing against the ditch's
right, and in a rationed year whatever the account has left of its allotment.

The allotment limit is a volume and everything else here is a rate, so it is
turned into the rate that would just use it up over the run the order asks for.
An account with twenty acre feet left that orders for a week is held to what
twenty acre feet is worth over a week, which is the answer that makes an
irrigator shorten the run rather than lose the water.

The smallest of those wins, which is the only sensible rule when several of
them apply at once, and the answer says which one it was. An irrigator told his
order was cut wants to know whether to buy shares, call the commissioner, or
wait for somebody upstream to finish.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from ..errors import PolicyError
from ..model.account import ShareRegister
from ..model.ditch import DitchSystem
from ..model.order import OrderBook, WaterOrder
from ..units import acre_feet_to_cfs, round_rate
from ..wateryear import IrrigationSeason

DEFAULT_NOTICE_HOURS = Decimal("24")
DEFAULT_CFS_PER_SHARE = Decimal("0.25")


@dataclass(frozen=True, slots=True)
class IntakeRules:
    """The district's own rules about taking an order."""

    notice_hours: Decimal = DEFAULT_NOTICE_HOURS
    cfs_per_share: Decimal = DEFAULT_CFS_PER_SHARE
    allow_short_notice: bool = False

    def entitlement(self, shares: Decimal) -> Decimal:
        return round_rate(shares * self.cfs_per_share)


@dataclass(frozen=True, slots=True)
class Limit:
    """One thing that held an order down."""

    name: str
    rate_cfs: Decimal
    explanation: str


def _limits(
    order: WaterOrder,
    rules: IntakeRules,
    register: ShareRegister,
    system: DitchSystem,
    book: OrderBook,
    curtailed_to: Decimal | None,
    allotment_left_af: Decimal | None = None,
) -> list[Limit]:
    day = order.span.start.date()
    shares = register.shares_at(order.turnout, day)
    limits = [
        Limit(
            "shares",
            rules.entitlement(shares),
            f"{shares} shares at {order.turnout} entitle {rules.entitlement(shares)} cfs",
        )
    ]
    gate = system.find_turnout(order.turnout)[1]
    limits.append(
        Limit(
            "turnout", gate.capacity_cfs, f"turnout {order.turnout} passes {gate.capacity_cfs} cfs"
        )
    )
    ditch = system.find_turnout(order.turnout)[0]
    already = sum(
        (
            item.running_cfs
            for item in book.overlapping(order.turnout, order.span)
            if item.order_id != order.order_id
        ),
        Decimal("0"),
    )
    spare = ditch.capacity_cfs - already
    limits.append(
        Limit(
            "lateral",
            spare if spare > 0 else Decimal("0"),
            f"ditch {ditch.code} has {round_rate(spare)} cfs left over orders already answered",
        )
    )
    if curtailed_to is not None:
        limits.append(
            Limit(
                "curtailment",
                curtailed_to,
                f"a curtailment holds {order.turnout} to {curtailed_to} cfs",
            )
        )
    if allotment_left_af is not None:
        spare = allotment_left_af if allotment_left_af > 0 else Decimal("0")
        limits.append(
            Limit(
                "allotment",
                acre_feet_to_cfs(spare, order.span.seconds) if spare > 0 else Decimal("0"),
                f"account {order.account} has {spare} acre feet of its allotment left",
            )
        )
    return limits


def answer_order(
    order: WaterOrder,
    rules: IntakeRules,
    register: ShareRegister,
    season: IrrigationSeason,
    system: DitchSystem,
    book: OrderBook,
    curtailed_to: Decimal | None = None,
    allotment_left_af: Decimal | None = None,
) -> WaterOrder:
    """Decide what an order may run, and say what decided it."""

    account = register.account(order.account)
    if not account.takes_delivery:
        return order.refuse(f"account {order.account} is {account.status.value}")
    if not season.covers(order.span.start.date()):
        return order.refuse(
            f"the season for {season.water_year} runs {season.opened} to {season.closed}"
        )
    if not season.covers(order.span.end.date()) and order.span.end.date() > season.closed:
        return order.refuse(f"the run would end after the season closes on {season.closed}")
    if order.notice_hours < rules.notice_hours and not rules.allow_short_notice:
        return order.refuse(
            f"{order.notice_hours} hours notice, and the district asks for {rules.notice_hours}"
        )
    limits = _limits(order, rules, register, system, book, curtailed_to, allotment_left_af)
    binding = min(limits, key=lambda item: item.rate_cfs)
    if binding.rate_cfs <= 0:
        return order.refuse(binding.explanation)
    if binding.rate_cfs >= order.requested_cfs:
        return order.accept(order.requested_cfs, "as ordered")
    return order.accept(binding.rate_cfs, binding.explanation)


def binding_limit(
    order: WaterOrder,
    rules: IntakeRules,
    register: ShareRegister,
    system: DitchSystem,
    book: OrderBook,
    curtailed_to: Decimal | None = None,
    allotment_left_af: Decimal | None = None,
) -> Limit:
    """Which rule is holding an order down, for somebody who wants to argue."""

    limits = _limits(order, rules, register, system, book, curtailed_to, allotment_left_af)
    return min(limits, key=lambda item: item.rate_cfs)


def receive(
    book: OrderBook,
    order: WaterOrder,
    rules: IntakeRules,
    register: ShareRegister,
    season: IrrigationSeason,
    system: DitchSystem,
    curtailed_to: Decimal | None = None,
    allotment_left_af: Decimal | None = None,
) -> tuple[OrderBook, WaterOrder]:
    """Put an order in the book with the office's answer on it."""

    if any(item.order_id == order.order_id for item in book.orders):
        raise PolicyError(f"order {order.order_id} is already in the book")
    answered = answer_order(
        order, rules, register, season, system, book, curtailed_to, allotment_left_af
    )
    return book.add(answered), answered
