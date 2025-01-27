"""The commands the water commissioner uses.

Placing a call, seeing what it would take, serving the notices and lifting them
again. The interesting one is place: it works the call against the creek as it
actually is, which means somebody has to tell it what everybody is taking, and
it will come back futile as often as it comes back honoured.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

import click

from ..errors import PolicyError
from ..ids import DecreeNumber
from ..priority.call import Call, CallOutcome, evaluate_call
from ..priority.curtail import notices_from
from ..store.repo_curtail import lift_call, load_register, serve_notice, standing_at
from ..store.repo_ditch import load_stream
from ..store.repo_rights import load_active_ladder, load_right
from ..wateryear import parse_instant
from .context import Context
from .render import Align, Column, field_list, rate, render_table


def _taking(pairs: tuple[str, ...]) -> dict[DecreeNumber, Decimal]:
    found: dict[DecreeNumber, Decimal] = {}
    for pair in pairs:
        decree, _, amount = pair.partition("=")
        if not amount:
            raise PolicyError(f"{pair!r} is not a diversion, write it as decree=cfs")
        found[DecreeNumber.parse(decree)] = Decimal(amount)
    return found


@click.group()
def call() -> None:
    """Calls on the stream, and the notices that answer them."""


@call.command("place")
@click.option("--decree", required=True, help="The right placing the call.")
@click.option("--arriving", required=True, help="What is reaching its headgate, in cfs.")
@click.option("--taking", multiple=True, help="A diversion as decree=cfs.")
@click.option("--at", "placed_at", default=None, help="When the call was placed.")
@click.option("--needed-by", default=None, help="When the water has to be there.")
@click.option("--stream", "stream_name", default="the creek", help="The stream's name.")
@click.option("--serve", is_flag=True, help="Serve the notices if it is honoured.")
@click.option("--notice-hours", default=24, show_default=True, help="Notice period.")
@click.pass_obj
def place(
    context: Context,
    decree: str,
    arriving: str,
    taking: tuple[str, ...],
    placed_at: str | None,
    needed_by: str | None,
    stream_name: str,
    serve: bool,
    notice_hours: int,
) -> None:
    """Work a call against the creek as it stands."""

    when = parse_instant(placed_at) if placed_at is not None else datetime.now()
    with context.open_current() as connection:
        calling = load_right(connection, DecreeNumber.parse(decree))
        stream = load_stream(connection, stream_name)
        decision = evaluate_call(
            stream,
            load_active_ladder(connection),
            Call(
                decree_owner=calling,
                placed_at=when,
                needed_by=parse_instant(needed_by) if needed_by is not None else None,
            ),
            _taking(taking),
            Decimal(arriving),
        )
        click.echo(
            field_list(
                [
                    ("call by", str(calling.decree)),
                    ("outcome", decision.outcome.value),
                    ("short", f"{rate(decision.shortfall_cfs)} cfs"),
                    ("would shut", f"{rate(decision.curtailed_cfs)} cfs"),
                    ("would deliver", f"{rate(decision.delivered_cfs)} cfs"),
                    ("because", decision.reason),
                ]
            )
        )
        if not decision.curtailments:
            return
        click.echo()
        columns = [
            Column("junior"),
            Column("shut", Align.RIGHT),
            Column("delivered", Align.RIGHT),
            Column("arrives"),
        ]
        click.echo(
            render_table(
                columns,
                [
                    [
                        str(item.right.decree),
                        rate(item.curtailed_cfs),
                        rate(item.delivered_cfs),
                        f"{item.arrives_at:%Y-%m-%d %H:%M}",
                    ]
                    for item in decision.curtailments
                ],
            )
        )
        if not serve:
            return
        if decision.outcome is not CallOutcome.HONOURED:
            raise PolicyError(
                f"the call came back {decision.outcome.value}, so there is nothing to serve"
            )
        for notice in notices_from(decision, when, notice_hours):
            serve_notice(connection, notice)
        click.echo(f"\n{len(decision.curtailments)} notices served")


@call.command("lift")
@click.option("--decree", required=True, help="The right whose call is over.")
@click.option("--at", "lifted_at", default=None, help="When it was lifted.")
@click.pass_obj
def lift(context: Context, decree: str, lifted_at: str | None) -> None:
    """Lift every notice served for one call."""

    when = parse_instant(lifted_at) if lifted_at is not None else datetime.now()
    with context.open_current() as connection:
        lifted = lift_call(connection, DecreeNumber.parse(decree), when)
        if not lifted:
            click.echo(f"no notices were standing for the call by {decree}")
            return
        click.echo(f"{lifted} notices lifted")


@call.command("standing")
@click.option("--at", "moment", default=None, help="The moment to look at.")
@click.pass_obj
def standing(context: Context, moment: str | None) -> None:
    """What curtailments are in force."""

    when = parse_instant(moment) if moment is not None else datetime.now()
    with context.open_current() as connection:
        notices = standing_at(connection, when)
        register = load_register(connection)
    if not notices:
        click.echo(f"nothing was curtailed at {when:%Y-%m-%d %H:%M}")
        return
    columns = [
        Column("decree"),
        Column("called by"),
        Column("shut", Align.RIGHT),
        Column("allowed", Align.RIGHT),
        Column("since"),
    ]
    rows = [
        [
            str(item.decree),
            str(item.called_by),
            rate(item.curtailed_cfs),
            rate(register.allowed_rate(item.decree, when)),
            f"{item.effective_at:%Y-%m-%d %H:%M}",
        ]
        for item in notices
    ]
    click.echo(render_table(columns, rows))


def register_commands(group: click.Group) -> None:
    """Hang the call commands off the main group."""

    group.add_command(call)
