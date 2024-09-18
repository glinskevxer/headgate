"""The report commands.

Each of these builds its answer out of the book and prints it. None of them
writes anything, so a clerk can run them against a district's live file in the
middle of the season without thinking about it.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

import click

from ..carriage.apportion import LossPolicy, apportion, measured_loss
from ..cli.render import Align, Column, field_list, rate, render_table, volume
from ..errors import PolicyError
from ..ids import TurnoutCode
from ..report.season import build
from ..store.assemble import build_ledger, headgate_volume, turnouts_without_a_device
from ..store.repo_ditch import load_system
from ..store.repo_orders import orders_running_at
from ..store.repo_season import load_season
from ..wateryear import Span, parse_instant
from .context import Context, district_name

POLICY_NAMES = [item.value.replace("_", "-") for item in LossPolicy]


def _policy(name: str) -> LossPolicy:
    return LossPolicy(name.replace("-", "_"))


@click.group()
def report() -> None:
    """Print what the book says."""


@report.command("season")
@click.argument("water_year", type=int)
@click.option(
    "--loss",
    "loss_policy",
    type=click.Choice(POLICY_NAMES),
    default="by-leg",
    show_default=True,
    help="How the ditch loss is charged out.",
)
@click.pass_obj
def season_report(context: Context, water_year: int, loss_policy: str) -> None:
    """The season report, headgate to turnout."""

    with context.open_current() as connection:
        season = load_season(connection, water_year)
        span = season.as_span()
        ledger = build_ledger(connection, span)
        volumes = ledger.volumes()
        headgate = headgate_volume(connection, span)
        loss = measured_loss(headgate.total_af, volumes)
        split = apportion(volumes, loss, _policy(loss_policy), system=load_system(connection))
        district = district_name(connection) or "this district"
        built = build(
            water_year, district, ledger, split, headgate.total_af, load_system(connection)
        )
        click.echo(field_list(built.summary()))
        click.echo()
        columns = [
            Column("turnout"),
            Column("delivered", Align.RIGHT),
            Column("measured", Align.RIGHT),
            Column("estimated", Align.RIGHT),
            Column("loss", Align.RIGHT),
            Column("charged", Align.RIGHT),
            Column("gap hours", Align.RIGHT),
        ]
        click.echo(render_table(columns, built.rows()))


@report.command("turnout")
@click.argument("turnout_code")
@click.option("--from", "run_from", required=True, help="Start of the span to report.")
@click.option("--to", "run_to", required=True, help="End of the span to report.")
@click.pass_obj
def turnout_report(context: Context, turnout_code: str, run_from: str, run_to: str) -> None:
    """One turnout's record over a span, segment by segment."""

    turnout = TurnoutCode.parse(turnout_code)
    span = Span(parse_instant(run_from), parse_instant(run_to))
    with context.open_current() as connection:
        ledger = build_ledger(connection, span)
        record = ledger.for_turnout(turnout)
        click.echo(
            field_list(
                [
                    ("turnout", str(record.turnout)),
                    ("device", str(record.device)),
                    ("delivered", f"{volume(record.total_af)} acre feet"),
                    ("measured", f"{volume(record.measured_af)} acre feet"),
                    ("estimated", f"{volume(record.estimated_af)} acre feet"),
                    ("record", record.provenance.value),
                    ("gap", f"{record.unaccounted_hours} hours"),
                ]
            )
        )
        click.echo()
        columns = [
            Column("from"),
            Column("to"),
            Column("rate", Align.RIGHT),
            Column("acre feet", Align.RIGHT),
            Column("record"),
            Column("why"),
        ]
        rows = [
            [
                f"{piece.span.start:%Y-%m-%d %H:%M}",
                f"{piece.span.end:%Y-%m-%d %H:%M}",
                rate(piece.rate_cfs),
                volume(piece.volume_af),
                piece.provenance.value,
                piece.reason,
            ]
            for piece in record.volume.segments
        ]
        click.echo(render_table(columns, rows))


@report.command("gaps")
@click.argument("water_year", type=int)
@click.pass_obj
def gaps(context: Context, water_year: int) -> None:
    """Turnouts nothing is measuring, and turnouts with holes in the record."""

    with context.open_current() as connection:
        span = load_season(connection, water_year).as_span()
        unmeasured = turnouts_without_a_device(connection, span)
        ledger = build_ledger(connection, span)
        holes = [record for record in ledger.records if record.unaccounted_hours > 0]
        if not unmeasured and not holes:
            click.echo(f"every turnout was measured all through {water_year}")
            return
        for turnout in unmeasured:
            click.echo(f"{turnout}: nothing measuring it")
        for record in holes:
            if record.turnout in unmeasured:
                continue
            click.echo(f"{record.turnout}: {record.unaccounted_hours} hours unaccounted for")


@report.command("running")
@click.option("--at", "moment", default=None, help="The moment to look at, default now.")
@click.pass_obj
def running(context: Context, moment: str | None) -> None:
    """What is running right now, off the answered orders."""

    at = parse_instant(moment) if moment is not None else datetime.now()
    with context.open_current() as connection:
        orders = orders_running_at(connection, at)
        if not orders:
            click.echo(f"nothing was running at {at:%Y-%m-%d %H:%M}")
            return
        columns = [
            Column("turnout"),
            Column("account", Align.RIGHT),
            Column("rate", Align.RIGHT),
            Column("until"),
        ]
        rows = [
            [
                str(item.turnout),
                str(item.account),
                rate(item.running_cfs),
                f"{item.span.end:%Y-%m-%d %H:%M}",
            ]
            for item in orders
        ]
        click.echo(render_table(columns, rows))
        total = sum((item.running_cfs for item in orders), Decimal("0"))
        click.echo(f"\n{rate(total)} cfs running at {len(orders)} turnouts")


def register(group: click.Group) -> None:
    """Hang the report commands off the main group."""

    group.add_command(report)


def check_policy(name: str) -> LossPolicy:
    """Turn a command line word into a policy, or say what the words are."""

    try:
        return _policy(name)
    except ValueError as exc:
        raise PolicyError(
            f"{name} is not a loss rule, try one of {', '.join(POLICY_NAMES)}"
        ) from exc
