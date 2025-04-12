"""The report commands.

Each of these builds its answer out of the book and prints it. None of them
writes anything, so a clerk can run them against a district's live file in the
middle of the season without thinking about it.
"""

from __future__ import annotations

import sqlite3
from datetime import date, datetime
from decimal import Decimal

import click

from ..analysis.compare import SeasonTotals, compare
from ..audit.journal import EntryKind
from ..carriage.apportion import LossPolicy, apportion, measured_loss
from ..cli.render import Align, Column, field_list, rate, render_table, volume
from ..errors import PolicyError
from ..ids import AccountNumber, DecreeNumber, TurnoutCode
from ..report.commissioner import build_day
from ..report.ledger import build as ledger_report
from ..report.season import build
from ..report.statement import build as build_statement
from ..store.assemble import (
    build_ledger,
    headgate_volume,
    turnout_owners,
    turnouts_without_a_device,
)
from ..store.repo_accounts import load_register
from ..store.repo_curtail import load_register as load_curtailments
from ..store.repo_ditch import load_system
from ..store.repo_journal import load_journal
from ..store.repo_orders import orders_running_at
from ..store.repo_payments import account_ledger
from ..store.repo_rights import load_active_ladder
from ..store.repo_season import load_season
from ..wateryear import Span, parse_day, parse_instant
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


@report.command("compare")
@click.option("--from", "before_year", required=True, type=int, help="The earlier season.")
@click.option("--to", "after_year", required=True, type=int, help="The later season.")
@click.option(
    "--tolerance",
    default="20",
    show_default=True,
    help="Percentage a turnout may move beyond the district before it is flagged.",
)
@click.pass_obj
def compare_seasons(context: Context, before_year: int, after_year: int, tolerance: str) -> None:
    """Line two seasons up and say which turnouts moved on their own."""

    with context.open_current() as connection:
        earlier = _season_totals(connection, before_year)
        later = _season_totals(connection, after_year)
    found = compare(earlier, later)
    click.echo(field_list(found.summary()))
    click.echo()
    columns = [
        Column("turnout"),
        Column(str(before_year), Align.RIGHT),
        Column(str(after_year), Align.RIGHT),
        Column("change", Align.RIGHT),
        Column("against district", Align.RIGHT),
    ]
    rows = [
        [
            str(item.turnout),
            volume(item.before_af),
            volume(item.after_af),
            f"{item.change}",
            f"{item.against_the_district}",
        ]
        for item in found.changes
    ]
    click.echo(render_table(columns, rows))
    flagged = found.out_of_step(Decimal(tolerance))
    if not flagged:
        click.echo("\nevery turnout moved with the district")
        return
    click.echo()
    for item in flagged:
        click.echo(f"{item.turnout} moved {item.against_the_district} percent against the district")


def _season_totals(connection: sqlite3.Connection, water_year: int) -> SeasonTotals:
    """Total a season out of the book, for a comparison to line up."""

    span = load_season(connection, water_year).as_span()
    ledger = build_ledger(connection, span)
    headgate = headgate_volume(connection, span)
    return SeasonTotals(
        water_year=water_year,
        headgate_af=headgate.total_af,
        delivered_af=ledger.total_af,
        by_turnout=ledger.volumes(),
    )


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


@report.command("day")
@click.option("--on", "day", required=True, help="The day to report.")
@click.option("--flow", required=True, help="What the creek was carrying, in cfs.")
@click.option("--taking", multiple=True, help="A diversion as decree=cfs.")
@click.pass_obj
def day_report(context: Context, day: str, flow: str, taking: tuple[str, ...]) -> None:
    """The water commissioner's page for one day."""

    when = parse_day(day)
    diverting: dict[DecreeNumber, Decimal] = {}
    for pair in taking:
        decree, _, amount = pair.partition("=")
        if not amount:
            raise PolicyError(f"{pair!r} is not a diversion, write it as decree=cfs")
        diverting[DecreeNumber.parse(decree)] = Decimal(amount)
    with context.open_current() as connection:
        built = build_day(
            when,
            load_active_ladder(connection),
            diverting,
            load_curtailments(connection),
            Decimal(flow),
        )
    click.echo(field_list(built.summary()))
    click.echo()
    columns = [
        Column("decree"),
        Column("owner"),
        Column("decreed", Align.RIGHT),
        Column("allowed", Align.RIGHT),
        Column("taking", Align.RIGHT),
        Column("over", Align.RIGHT),
        Column("curtailed"),
    ]
    click.echo(render_table(columns, built.rows()))
    if not built.in_compliance:
        click.echo(f"\n{len(built.over_diverting)} rights are over what they are allowed")


@report.command("account")
@click.option("--account", "account_number", required=True, help="Whose statement.")
@click.option("--year", "water_year", required=True, type=int, help="Water year.")
@click.option("--as-of", default=None, help="The day to work the balance to.")
@click.option("--due", default=None, help="The day the bill was due.")
@click.pass_obj
def account_report(
    context: Context,
    account_number: str,
    water_year: int,
    as_of: str | None,
    due: str | None,
) -> None:
    """One account's statement for a season."""

    account = AccountNumber.parse(account_number)
    with context.open_current() as connection:
        season = load_season(connection, water_year)
        span = season.as_span()
        ledger = build_ledger(connection, span)
        volumes = ledger.volumes()
        headgate = headgate_volume(connection, span)
        split = apportion(
            volumes,
            measured_loss(headgate.total_af, volumes),
            LossPolicy.BY_LEG,
            system=load_system(connection),
        )
        owners = turnout_owners(connection, season.opened)
        mine = tuple(turnout for turnout, holders in owners.items() if account in holders)
        if not mine:
            raise PolicyError(f"account {account} was not delivered anywhere in {water_year}")
        register = load_register(connection)
        holder = register.account(account)
        statement = build_statement(
            account=account,
            name=holder.name,
            water_year=water_year,
            shares=register.shares_of(account, season.opened),
            ledger=account_ledger(connection, account),
            deliveries=ledger,
            turnouts=mine,
            charged_loss={turnout: split.for_turnout(turnout).loss_af for turnout in mine},
            due_on=parse_day(due) if due is not None else date(water_year, 12, 1),
            as_of=parse_day(as_of) if as_of is not None else date.today(),
        )
    click.echo(field_list(statement.summary()))
    click.echo()
    columns = [
        Column("turnout"),
        Column("delivered", Align.RIGHT),
        Column("measured", Align.RIGHT),
        Column("estimated", Align.RIGHT),
        Column("loss", Align.RIGHT),
        Column("charged", Align.RIGHT),
    ]
    click.echo(render_table(columns, statement.rows()))


@report.command("journal")
@click.option("--subject", default=None, help="Only entries about one subject.")
@click.option(
    "--kind",
    "kind_name",
    type=click.Choice([item.value for item in EntryKind]),
    default=None,
    help="Only entries of one kind.",
)
@click.option("--from", "first", default=None, help="Earliest entry to print.")
@click.option("--to", "last", default=None, help="Latest entry to print.")
@click.pass_obj
def journal(
    context: Context,
    subject: str | None,
    kind_name: str | None,
    first: str | None,
    last: str | None,
) -> None:
    """Print the journal, or the part of it somebody asked about."""

    with context.open_current() as connection:
        built = ledger_report(
            load_journal(connection).entries,
            subject=subject,
            kind=EntryKind(kind_name) if kind_name is not None else None,
            first=parse_instant(first) if first is not None else None,
            last=parse_instant(last) if last is not None else None,
        )
    if built.is_empty:
        click.echo("nothing in the journal answers that")
        return
    click.echo(field_list(built.summary()))
    click.echo()
    columns = [
        Column("entry", Align.RIGHT),
        Column("day"),
        Column("kind"),
        Column("subject"),
        Column("water", Align.RIGHT),
        Column("money", Align.RIGHT),
        Column("note"),
    ]
    click.echo(render_table(columns, built.rows()))


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
