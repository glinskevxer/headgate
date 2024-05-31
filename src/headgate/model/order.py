"""Water orders: what a shareholder asked for and what the office said.

An order is a request for a rate at a turnout over a stretch of time. It is
never edited into a different request. The office answers it, and the answer is
a new state on the same order, so the book still shows what was asked for when
somebody argues about it in September.

A reduced order is the interesting one. The office accepted it at less than the
rate asked for, which happens when the lateral is full or a curtailment is
standing, and both the request and the allowance are on the record.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime
from decimal import Decimal
from enum import Enum

from ..errors import NotFoundError, PolicyError, ValidationError
from ..ids import AccountNumber, TurnoutCode
from ..units import round_rate
from ..wateryear import Span


class OrderStatus(Enum):
    """Where an order stands."""

    REQUESTED = "requested"
    ACCEPTED = "accepted"
    REDUCED = "reduced"
    REFUSED = "refused"
    DELIVERED = "delivered"
    CANCELLED = "cancelled"

    @property
    def will_run(self) -> bool:
        return self in {OrderStatus.ACCEPTED, OrderStatus.REDUCED}

    @property
    def is_settled(self) -> bool:
        return self in {OrderStatus.DELIVERED, OrderStatus.REFUSED, OrderStatus.CANCELLED}


@dataclass(frozen=True, slots=True)
class WaterOrder:
    """One request for water at one turnout."""

    order_id: int
    account: AccountNumber
    turnout: TurnoutCode
    requested_cfs: Decimal
    span: Span
    placed_at: datetime
    status: OrderStatus = OrderStatus.REQUESTED
    allowed_cfs: Decimal | None = None
    note: str = ""

    def __post_init__(self) -> None:
        if self.order_id < 1:
            raise ValidationError(f"{self.order_id} is not an order number")
        if self.requested_cfs <= 0:
            raise ValidationError(f"order {self.order_id} asks for no water")
        if self.placed_at > self.span.start:
            raise ValidationError(
                f"order {self.order_id} was placed after the water was due to run"
            )
        if self.allowed_cfs is not None and self.allowed_cfs < 0:
            raise ValidationError(f"order {self.order_id} was allowed a negative rate")
        if self.status is OrderStatus.REDUCED and self.allowed_cfs is None:
            raise ValidationError(f"order {self.order_id} was reduced to nothing in particular")
        if self.status is OrderStatus.ACCEPTED and self.allowed_cfs is None:
            raise ValidationError(f"order {self.order_id} was accepted at no stated rate")

    @property
    def running_cfs(self) -> Decimal:
        """The rate that will actually be set, which is zero unless it runs."""

        if not self.status.will_run or self.allowed_cfs is None:
            return Decimal("0")
        return self.allowed_cfs

    @property
    def volume_af(self) -> Decimal:
        return (self.running_cfs * self.span.seconds / Decimal("43560")).quantize(Decimal("0.0001"))

    @property
    def notice_hours(self) -> Decimal:
        return (
            Decimal(str((self.span.start - self.placed_at).total_seconds())) / Decimal("3600")
        ).quantize(Decimal("0.01"))

    def accept(self, allowed_cfs: Decimal, note: str = "") -> WaterOrder:
        """Answer an order, reducing it if the allowance is short."""

        if self.status is not OrderStatus.REQUESTED:
            raise PolicyError(f"order {self.order_id} has already been answered")
        allowed = round_rate(allowed_cfs)
        if allowed <= 0:
            return self.refuse(note or "no water was available")
        status = OrderStatus.ACCEPTED if allowed >= self.requested_cfs else OrderStatus.REDUCED
        return replace(self, status=status, allowed_cfs=min(allowed, self.requested_cfs), note=note)

    def refuse(self, note: str) -> WaterOrder:
        if self.status is not OrderStatus.REQUESTED:
            raise PolicyError(f"order {self.order_id} has already been answered")
        return replace(self, status=OrderStatus.REFUSED, allowed_cfs=Decimal("0"), note=note)

    def cancel(self, note: str = "") -> WaterOrder:
        if self.status.is_settled:
            raise PolicyError(f"order {self.order_id} is already {self.status.value}")
        return replace(self, status=OrderStatus.CANCELLED, note=note)

    def mark_delivered(self) -> WaterOrder:
        if not self.status.will_run:
            raise PolicyError(f"order {self.order_id} never ran, so it cannot be delivered")
        return replace(self, status=OrderStatus.DELIVERED)


@dataclass(frozen=True, slots=True)
class OrderBook:
    """Every order on the ditch this season."""

    orders: tuple[WaterOrder, ...] = ()

    def __post_init__(self) -> None:
        seen: set[int] = set()
        for order in self.orders:
            if order.order_id in seen:
                raise ValidationError(f"order {order.order_id} appears twice")
            seen.add(order.order_id)

    @property
    def next_number(self) -> int:
        return max((order.order_id for order in self.orders), default=0) + 1

    def order(self, order_id: int) -> WaterOrder:
        for order in self.orders:
            if order.order_id == order_id:
                return order
        raise NotFoundError("order", str(order_id))

    def add(self, order: WaterOrder) -> OrderBook:
        return replace(self, orders=(*self.orders, order))

    def replace_order(self, order: WaterOrder) -> OrderBook:
        self.order(order.order_id)
        return replace(
            self,
            orders=tuple(
                order if item.order_id == order.order_id else item for item in self.orders
            ),
        )

    def for_turnout(self, turnout: TurnoutCode) -> tuple[WaterOrder, ...]:
        return tuple(order for order in self.orders if order.turnout == turnout)

    def for_account(self, account: AccountNumber) -> tuple[WaterOrder, ...]:
        return tuple(order for order in self.orders if order.account == account)

    def running_at(self, moment: datetime) -> tuple[WaterOrder, ...]:
        return tuple(
            order for order in self.orders if order.status.will_run and order.span.contains(moment)
        )

    def overlapping(self, turnout: TurnoutCode, span: Span) -> tuple[WaterOrder, ...]:
        return tuple(
            order
            for order in self.orders
            if order.turnout == turnout
            and not order.status.is_settled
            and order.span.overlaps(span)
        )

    def waiting(self) -> tuple[WaterOrder, ...]:
        return tuple(order for order in self.orders if order.status is OrderStatus.REQUESTED)

    def ordered_rate_at(self, turnout: TurnoutCode, moment: datetime) -> Decimal:
        return round_rate(
            sum(
                (
                    order.running_cfs
                    for order in self.running_at(moment)
                    if order.turnout == turnout
                ),
                Decimal("0"),
            )
        )
