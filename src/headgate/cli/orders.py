"""The order commands.

Placing an order and answering it are separate commands on purpose. The office
takes orders over the telephone all afternoon and answers them in one pass in
the evening, once it knows what the creek is doing, and an order that was taken
but not yet answered is a real state the book has to be able to hold.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime
from decimal import Decimal

import click

from ..errors import HeadgateError, PolicyError
from ..ids import AccountNumber, TurnoutCode
from ..model.order import WaterOrder
from ..orders.allocation import ShortagePolicy
from ..orders.allocation import allocate as allocate_day
from ..orders.intake import IntakeRules, answer_order
from ..store.assemble import shares_by_turnout
from ..store.repo_accounts import load_register
from ..store.repo_allotment import load_ledger as load_allotment
from ..store.repo_ditch import load_system
from ..store.repo_orders import (
    load_book,
    load_order,
    next_order_number,
    orders_running_at,
    save_order,
    waiting_orders,
)
from ..store.repo_season import season_for
from ..wateryear import Span, parse_instant
from .context import Context
from .render import Align, Column, field_list, rate, render_table, truncate


@click.group()
def order() -> None:
    """Take and answer orders for water."""


@order.command("place")
@click.option("--account", "account_number", required=True, help="Shareholder account number.")
@click.option("--turnout", "turnout_code", required=True, help="Turnout the water runs to.")
@click.option("--rate", "requested", required=True, help="Rate asked for, in cubic feet a second.")
@click.option("--from", "run_from", required=True, help="When the run starts.")
@click.option("--to", "run_to", required=True, help="When the run ends.")
@click.option("--placed", default=None, help="When the order was taken, if not now.")
@click.pass_obj
def place(
    context: Context,
    account_number: str,
    turnout_code: str,
    requested: str,
    run_from: str,
    run_to: str,
    placed: str | None,
) -> None:
    """Take an order and leave it waiting for an answer."""

    with context.open_current() as connection:
        number = next_order_number(connection)
        placed_at = parse_instant(placed) if placed is not None else datetime.now()
        taken = WaterOrder(
            order_id=number,
            account=AccountNumber.parse(account_number),
            turnout=TurnoutCode.parse(turnout_code),
            requested_cfs=Decimal(requested),
            span=Span(parse_instant(run_from), parse_instant(run_to)),
            placed_at=placed_at,
        )
        save_order(connection, taken)
        click.echo(f"order {number} taken for {taken.turnout} at {rate(taken.requested_cfs)} cfs")


@order.command("answer")
@click.argument("order_id", type=int)
@click.option("--curtailed-to", default=None, help="Rate a standing curtailment allows.")
@click.option("--notice-hours", default=None, help="Override the district's notice period.")
@click.pass_obj
def answer(
    context: Context, order_id: int, curtailed_to: str | None, notice_hours: str | None
) -> None:
    """Answer a waiting order against the book as it stands."""

    with context.open_current() as connection:
        waiting = load_order(connection, order_id)
        rules = IntakeRules(
            notice_hours=Decimal(notice_hours)
            if notice_hours is not None
            else IntakeRules().notice_hours
        )
        season = season_for(connection, waiting.span.start.date())
        left = _allotment_left(connection, season.water_year, waiting.account)
        answered = answer_order(
            waiting,
            rules,
            load_register(connection),
            season,
            load_system(connection),
            load_book(connection, waiting.span),
            Decimal(curtailed_to) if curtailed_to is not None else None,
            left,
        )
        save_order(connection, answered)
        click.echo(
            field_list(
                [
                    ("order", str(answered.order_id)),
                    ("turnout", str(answered.turnout)),
                    ("asked for", f"{rate(answered.requested_cfs)} cfs"),
                    ("answered", answered.status.value),
                    ("allowed", f"{rate(answered.allowed_cfs)} cfs"),
                    ("because", answered.note),
                ]
            )
        )


@order.command("cancel")
@click.argument("order_id", type=int)
@click.option("--note", default="", help="Why it was cancelled.")
@click.pass_obj
def cancel(context: Context, order_id: int, note: str) -> None:
    """Cancel an order that is not going to run."""

    with context.open_current() as connection:
        cancelled = load_order(connection, order_id).cancel(note)
        save_order(connection, cancelled)
        click.echo(f"order {order_id} cancelled")


@order.command("allocate")
@click.option("--at", "moment", required=True, help="The moment the ditch is being set.")
@click.option("--supply", required=True, help="What the ditch has to hand out, in cfs.")
@click.option(
    "--policy",
    type=click.Choice([item.value.replace("_", "-") for item in ShortagePolicy]),
    default="pro-rata",
    show_default=True,
    help="How a short day is cut.",
)
@click.option(
    "--minimum-head",
    default="0.5",
    show_default=True,
    help="Below this a set is dropped rather than cut.",
)
@click.pass_obj
def allocate(context: Context, moment: str, supply: str, policy: str, minimum_head: str) -> None:
    """Cut the answered orders down to the water that showed up."""

    at = parse_instant(moment)
    with context.open_current() as connection:
        running = list(orders_running_at(connection, at))
        if not running:
            raise PolicyError(f"no order was due to run at {at:%Y-%m-%d %H:%M}")
        season = season_for(connection, at.date())
        shares = shares_by_turnout(connection, season.opened)
        result = allocate_day(
            running,
            Decimal(supply),
            ShortagePolicy(policy.replace("-", "_")),
            shares,
            Decimal(minimum_head),
        )
    columns = [
        Column("order", Align.RIGHT),
        Column("turnout"),
        Column("answered", Align.RIGHT),
        Column("running", Align.RIGHT),
        Column("why"),
    ]
    rows = [
        [
            str(item.order_id),
            str(item.turnout),
            rate(item.answered_cfs),
            rate(item.running_cfs),
            item.reason,
        ]
        for item in result.cuts
    ]
    click.echo(render_table(columns, rows))
    click.echo()
    click.echo(
        f"{rate(result.running_cfs)} of {rate(result.answered_cfs)} cfs running, "
        f"{len(result.dropped)} sets dropped"
    )


@order.command("list")
@click.option("--waiting", "only_waiting", is_flag=True, help="Only orders not yet answered.")
@click.pass_obj
def list_orders(context: Context, only_waiting: bool) -> None:
    """List the orders in the book."""

    with context.open_current() as connection:
        orders = waiting_orders(connection) if only_waiting else load_book(connection).orders
        if not orders:
            click.echo("no orders")
            return
        click.echo(_order_table(orders))


def _allotment_left(
    connection: sqlite3.Connection, water_year: int, account: AccountNumber
) -> Decimal | None:
    """What the account has left this year, or nothing if it is not a rationed one."""

    try:
        return load_allotment(connection, water_year).remaining_af(account)
    except HeadgateError:
        return None


def _order_table(orders: tuple[WaterOrder, ...]) -> str:
    columns = [
        Column("id", Align.RIGHT),
        Column("account", Align.RIGHT),
        Column("turnout"),
        Column("asked", Align.RIGHT),
        Column("allowed", Align.RIGHT),
        Column("status"),
        Column("note"),
    ]
    rows = [
        [
            str(item.order_id),
            str(item.account),
            str(item.turnout),
            rate(item.requested_cfs),
            rate(item.allowed_cfs),
            item.status.value,
            truncate(item.note, 28),
        ]
        for item in orders
    ]
    return render_table(columns, rows)


def register(group: click.Group) -> None:
    """Hang the order commands off the main group."""

    group.add_command(order)


def rows_for(connection: sqlite3.Connection) -> int:
    """How many orders are in the book, for the status command."""

    return len(load_book(connection).orders)
