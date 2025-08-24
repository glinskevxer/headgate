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
from ..analysis.efficiency import review as duty_review
from ..audit.journal import EntryKind
from ..carriage.apportion import LossPolicy, apportion, measured_loss
from ..carriage.apportion import expected_loss as expected_loss_af
from ..cli.render import Align, Column, as_json, field_list, rate, render_table, volume
from ..duty.hcu import analyse
from ..errors import NotFoundError, PolicyError
from ..ids import AccountNumber, DecreeNumber, TurnoutCode
from ..model.device import Device
from ..report.balance import build as build_balance
from ..report.board import build as build_packet
from ..report.commissioner import build_day
from ..report.exceptions import build as build_exceptions
from ..report.ledger import build as ledger_report
from ..report.runsheet import build as build_runsheet
from ..report.season import build
from ..report.statement import build as build_statement
from ..store.assemble import (
    build_ledger,
    consumptive_use_records,
    headgate_volume,
    season_picture,
    turnout_owners,
    turnouts_without_a_device,
)
from ..store.repo_accounts import load_place_of_use, load_register
from ..store.repo_bills import load_run
from ..store.repo_curtail import load_register as load_curtailments
from ..store.repo_devices import device_at_turnout, load_devices
from ..store.repo_ditch import load_system
from ..store.repo_journal import load_journal
from ..store.repo_orders import orders_running_at
from ..store.repo_payments import account_ledger
from ..store.repo_rights import load_active_ladder
from ..store.repo_rotation import running_at as rotation_running_at
from ..store.repo_season import load_season
from ..wateryear import Span, parse_day, parse_instant
from .context import Context, district_name

POLICY_NAMES = [item.value.replace("_", "-") for item in LossPolicy]


def _policy(name: str) -> LossPolicy:
    return LossPolicy(name.replace("-", "_"))


@click.group()
def report() -> None:
    """Print what the book says."""


def show(
    summary: list[tuple[str, str]],
    columns: list[Column],
    rows: list[list[str]],
    output: str = "text",
) -> None:
    """Print a report as a block and a table, or as json.

    Every report printed the same three lines and they drifted: one of them
    printed the table before the summary and two of them could not be asked for
    json at all. They all come through here now.
    """

    if output == "json":
        click.echo(as_json(summary, columns, rows))
        return
    click.echo(field_list(summary))
    click.echo()
    click.echo(render_table(columns, rows))


@report.command("season")
@click.argument("water_year", type=int)
@click.option(
    "--format",
    "output",
    type=click.Choice(["text", "json"]),
    default="text",
    show_default=True,
    help="How to print it.",
)
@click.option(
    "--loss",
    "loss_policy",
    type=click.Choice(POLICY_NAMES),
    default="by-leg",
    show_default=True,
    help="How the ditch loss is charged out.",
)
@click.pass_obj
def season_report(context: Context, water_year: int, output: str, loss_policy: str) -> None:
    """The season report, headgate to turnout."""

    with context.open_current() as connection:
        picture = season_picture(connection, water_year, _policy(loss_policy))
        district = district_name(connection) or "this district"
        built = build(
            water_year,
            district,
            picture.ledger,
            picture.apportionment,
            picture.headgate.total_af,
            picture.system,
        )
        columns = [
            Column("turnout"),
            Column("delivered", Align.RIGHT),
            Column("measured", Align.RIGHT),
            Column("estimated", Align.RIGHT),
            Column("loss", Align.RIGHT),
            Column("charged", Align.RIGHT),
            Column("gap hours", Align.RIGHT),
        ]
        show(built.summary(), columns, built.rows(), output)


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

    picture = season_picture(connection, water_year)
    return SeasonTotals(
        water_year=water_year,
        headgate_af=picture.headgate.total_af,
        delivered_af=picture.ledger.total_af,
        by_turnout=picture.volumes,
    )


@report.command("balance")
@click.option("--year", "water_year", required=True, type=int, help="Season to balance.")
@click.option(
    "--expected-loss",
    default=None,
    help="Share of the headgate the ditch keeps, default off the loss rates.",
)
@click.pass_obj
def balance(context: Context, water_year: int, expected_loss: str | None) -> None:
    """The water balance month by month, headgate down to the fields."""

    with context.open_current() as connection:
        picture = season_picture(connection, water_year)
        if expected_loss is not None:
            fraction = Decimal(expected_loss)
        elif picture.headgate.total_af > 0:
            fraction = (
                expected_loss_af(picture.system, picture.volumes) / picture.headgate.total_af
            ).quantize(Decimal("0.001"))
        else:
            fraction = Decimal("0")
        built = build_balance(water_year, picture.headgate, picture.ledger, fraction)
    columns = [
        Column("month", Align.RIGHT),
        Column("headgate", Align.RIGHT),
        Column("delivered", Align.RIGHT),
        Column("loss", Align.RIGHT),
        Column("expected", Align.RIGHT),
        Column("unexplained", Align.RIGHT),
        Column("carriage", Align.RIGHT),
    ]
    show(built.summary(), columns, built.rows())
    if not built.out_of_balance:
        click.echo("\nevery month is inside what the loss rates account for")
        return
    for month in built.out_of_balance:
        click.echo(
            f"\nmonth {month.month} lost {month.unexplained_af} acre feet nobody can account for"
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
    columns = [
        Column("decree"),
        Column("owner"),
        Column("decreed", Align.RIGHT),
        Column("allowed", Align.RIGHT),
        Column("taking", Align.RIGHT),
        Column("over", Align.RIGHT),
        Column("curtailed"),
    ]
    show(built.summary(), columns, built.rows())
    if not built.in_compliance:
        click.echo(f"\n{len(built.over_diverting)} rights are over what they are allowed")


@report.command("account")
@click.option("--account", "account_number", required=True, help="Whose statement.")
@click.option("--year", "water_year", required=True, type=int, help="Water year.")
@click.option("--as-of", default=None, help="The day to work the balance to.")
@click.option("--due", default=None, help="The day the bill was due.")
@click.option(
    "--format",
    "output",
    type=click.Choice(["text", "json"]),
    default="text",
    show_default=True,
    help="How to print it.",
)
@click.pass_obj
def account_report(
    context: Context,
    account_number: str,
    water_year: int,
    as_of: str | None,
    due: str | None,
    output: str,
) -> None:
    """One account's statement for a season."""

    account = AccountNumber.parse(account_number)
    with context.open_current() as connection:
        picture = season_picture(connection, water_year)
        season = picture.season
        ledger = picture.ledger
        split = picture.apportionment
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
    columns = [
        Column("turnout"),
        Column("delivered", Align.RIGHT),
        Column("measured", Align.RIGHT),
        Column("estimated", Align.RIGHT),
        Column("loss", Align.RIGHT),
        Column("charged", Align.RIGHT),
    ]
    show(statement.summary(), columns, statement.rows(), output)


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
    columns = [
        Column("entry", Align.RIGHT),
        Column("day"),
        Column("kind"),
        Column("subject"),
        Column("water", Align.RIGHT),
        Column("money", Align.RIGHT),
        Column("note"),
    ]
    show(built.summary(), columns, built.rows())


@report.command("hcu")
@click.option("--turnout", "turnout_code", required=True, help="The ground being studied.")
@click.option("--years", required=True, help="Water years, as first-last.")
@click.option(
    "--minimum", default=5, show_default=True, help="How many usable years the rule asks for."
)
@click.option("--count-curtailed", is_flag=True, help="Count the years spent curtailed.")
@click.pass_obj
def hcu(
    context: Context,
    turnout_code: str,
    years: str,
    minimum: int,
    count_curtailed: bool,
) -> None:
    """What the ground behind a turnout has actually consumed."""

    first, _, last = years.partition("-")
    if not last:
        raise PolicyError(f"{years!r} is not a study period, write it as first-last")
    turnout = TurnoutCode.parse(turnout_code)
    with context.open_current() as connection:
        records = consumptive_use_records(connection, turnout, range(int(first), int(last) + 1))
    if not records:
        raise PolicyError(f"there is no delivery record for {turnout} in those years")
    study = analyse(records, minimum_years=minimum, count_curtailed=count_curtailed)
    click.echo(
        field_list(
            [
                ("turnout", str(turnout)),
                ("study period", f"{first} to {last}"),
                ("years read", str(study.study_years)),
                ("years counted", str(study.counted_years)),
                ("consumptive use", f"{volume(study.average_af)} acre feet a year"),
            ]
        )
    )
    click.echo()
    columns = [
        Column("year", Align.RIGHT),
        Column("consumed", Align.RIGHT),
        Column("counted"),
        Column("why"),
    ]
    rows = [
        [
            str(item.water_year),
            volume(item.consumed_af),
            "yes" if item.counted else "no",
            item.reason,
        ]
        for item in study.findings
    ]
    click.echo(render_table(columns, rows))


@report.command("board")
@click.option("--year", "water_year", required=True, type=int, help="Season to report.")
@click.option("--on", "as_of", default=None, help="The day the packet is dated.")
@click.option(
    "--proved-floor",
    default="0.9",
    show_default=True,
    help="How much of the season has to be proved before adopting it.",
)
@click.pass_obj
def board(context: Context, water_year: int, as_of: str | None, proved_floor: str) -> None:
    """The packet the board reads before it adopts a season."""

    day = parse_day(as_of) if as_of is not None else date.today()
    with context.open_current() as connection:
        season = load_season(connection, water_year)
        span = season.as_span()
        ledger = build_ledger(connection, span)
        volumes = ledger.volumes()
        headgate = headgate_volume(connection, span)
        system = load_system(connection)
        split = apportion(
            volumes, measured_loss(headgate.total_af, volumes), LossPolicy.BY_LEG, system=system
        )
        built = build(
            water_year,
            district_name(connection) or "this district",
            ledger,
            split,
            headgate.total_af,
            system,
        )
        packet = build_packet(
            built,
            load_run(connection, water_year),
            build_exceptions(day, ledger, load_devices(connection)),
            Decimal(proved_floor),
        )
    click.echo(field_list(packet.summary()))
    for name, rows in packet.sections():
        if not rows:
            continue
        click.echo(f"\n{name}")
        for row in rows:
            click.echo("  " + "  ".join(row))
    if packet.can_be_adopted:
        click.echo("\nthis season is worth adopting as it stands")
        return
    click.echo("\nthis season is not worth adopting yet:")
    for reason in packet.reasons_not_to_adopt():
        click.echo(f"  {reason}")


@report.command("duty")
@click.option("--year", "water_year", required=True, type=int, help="Season to look at.")
@click.option("--on", "as_of", default=None, help="The day the ground is counted on.")
@click.pass_obj
def duty(context: Context, water_year: int, as_of: str | None) -> None:
    """What the ground needed against what it got."""

    with context.open_current() as connection:
        season = load_season(connection, water_year)
        day = parse_day(as_of) if as_of is not None else season.opened
        ledger = build_ledger(connection, season.as_span())
        place = load_place_of_use(connection)
        if not place.parcels:
            raise PolicyError("no parcels are recorded, so there is no duty to work out")
        found = duty_review(water_year, place, ledger.volumes(), day)
    click.echo(field_list(found.summary()))
    click.echo()
    columns = [
        Column("turnout"),
        Column("acres", Align.RIGHT),
        Column("needed", Align.RIGHT),
        Column("delivered", Align.RIGHT),
        Column("ratio", Align.RIGHT),
        Column("inches", Align.RIGHT),
    ]
    rows = [
        [
            str(item.turnout),
            f"{item.acres}",
            volume(item.required_af),
            volume(item.delivered_af),
            f"{item.ratio}",
            f"{item.depth_inches}",
        ]
        for item in found.duties
    ]
    click.echo(render_table(columns, rows))
    for item in found.short:
        click.echo(f"\n{item.describe()}")


@report.command("runsheet")
@click.option("--on", "day", required=True, help="The day the rider is driving.")
@click.option("--at", "moment", default=None, help="The moment to read the orders at.")
@click.option(
    "--from-rotation", is_flag=True, help="Take the rates off the rotation rather than the orders."
)
@click.pass_obj
def runsheet(context: Context, day: str, moment: str | None, from_rotation: bool) -> None:
    """What to set today, and to what gauge height."""

    when = parse_day(day)
    at = (
        parse_instant(moment)
        if moment is not None
        else datetime.combine(when, datetime.min.time()).replace(hour=6)
    )
    with context.open_current() as connection:
        wanted: dict[TurnoutCode, Decimal] = {}
        if from_rotation:
            for window in rotation_running_at(connection, at):
                wanted[window.turnout] = wanted.get(window.turnout, Decimal("0")) + window.rate_cfs
        else:
            for order in orders_running_at(connection, at):
                wanted[order.turnout] = wanted.get(order.turnout, Decimal("0")) + order.running_cfs
        devices: dict[TurnoutCode, Device] = {}
        for turnout in wanted:
            try:
                devices[turnout] = device_at_turnout(connection, turnout, when)
            except NotFoundError:
                continue
        sheet = build_runsheet(when, wanted, devices)
    if sheet.is_empty:
        click.echo(f"nothing to set on {when}")
        return
    columns = [
        Column("turnout"),
        Column("rate", Align.RIGHT),
        Column("device"),
        Column("staff", Align.RIGHT),
        Column("note"),
    ]
    show(sheet.summary(), columns, sheet.rows())
    for point in sheet.unsettable:
        click.echo(f"\n{point.describe()}")


@report.command("exceptions")
@click.option("--year", "water_year", required=True, type=int, help="Season to look at.")
@click.option("--on", "as_of", default=None, help="The day to report, default today.")
@click.option(
    "--lookahead",
    default=30,
    show_default=True,
    help="Days ahead to chase a calibration about to lapse.",
)
@click.pass_obj
def exceptions(context: Context, water_year: int, as_of: str | None, lookahead: int) -> None:
    """What wants doing this week, worst first."""

    day = parse_day(as_of) if as_of is not None else date.today()
    with context.open_current() as connection:
        span = load_season(connection, water_year).as_span()
        built = build_exceptions(
            day, build_ledger(connection, span), load_devices(connection), lookahead
        )
    if built.is_quiet:
        click.echo(f"nothing wants doing on {day}")
        return
    columns = [
        Column("when"),
        Column("subject"),
        Column("what"),
        Column("costs water"),
    ]
    click.echo(render_table(columns, built.rows()))
    click.echo()
    click.echo(f"{len(built.now)} want doing now, {len(built.costing_water)} are costing water")


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
