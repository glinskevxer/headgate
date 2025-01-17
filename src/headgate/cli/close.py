"""Closing the season from the command line.

This is the November command. It builds the delivery ledger out of the book,
charges the ditch loss out, bills every account and posts the lot to the
journal, in that order, and it will not do any of it twice.

A dry run does everything except write, which is how the clerk checks the
numbers against last year before the bills go out.
"""

from __future__ import annotations

from datetime import date, datetime

import click

from ..audit.journal import EntryKind
from ..carriage.apportion import LossPolicy
from ..errors import PolicyError
from ..season.close import close_season
from ..store.assemble import (
    build_ledger,
    headgate_volume,
    shares_by_account,
    shares_by_turnout,
    turnout_accounts,
)
from ..store.repo_bills import issued_on, save_run
from ..store.repo_ditch import load_system
from ..store.repo_journal import post
from ..store.repo_schedule import load_schedule
from ..store.repo_season import load_season
from ..wateryear import parse_day
from .context import Context, district_name
from .render import field_list, volume

POLICY_NAMES = [item.value.replace("_", "-") for item in LossPolicy]


@click.command("close")
@click.option("--year", "water_year", required=True, type=int, help="Water year to close.")
@click.option("--issued", default=None, help="The day the bills go out, default today.")
@click.option(
    "--loss",
    "loss_policy",
    type=click.Choice(POLICY_NAMES),
    default="by-leg",
    show_default=True,
    help="How the ditch loss is charged out.",
)
@click.option("--dry-run", is_flag=True, help="Work the numbers and write nothing.")
@click.pass_obj
def close(
    context: Context, water_year: int, issued: str | None, loss_policy: str, dry_run: bool
) -> None:
    """Close a season: total the water, charge the loss, bill everybody."""

    issued_day = parse_day(issued) if issued is not None else date.today()
    policy = LossPolicy(loss_policy.replace("-", "_"))
    with context.open_current() as connection:
        if issued_on(connection, water_year) is not None:
            raise PolicyError(
                f"the {water_year} season has already been billed, a change to it is a restatement"
            )
        season = load_season(connection, water_year)
        schedule = load_schedule(connection, water_year)
        span = season.as_span()
        ledger = build_ledger(connection, span)
        headgate = headgate_volume(connection, span)
        system = load_system(connection)
        closed = close_season(
            water_year=water_year,
            district=district_name(connection) or "this district",
            ledger=ledger,
            headgate_af=headgate.total_af,
            system=system,
            schedule=schedule,
            turnout_accounts=turnout_accounts(connection, season.opened),
            shares=shares_by_account(connection, season.opened),
            issued_on=issued_day,
            policy=policy,
            turnout_shares=shares_by_turnout(connection, season.opened),
        )
        click.echo(
            field_list(
                [
                    ("water year", str(water_year)),
                    ("headgate", f"{volume(closed.report.headgate_af)} acre feet"),
                    ("delivered", f"{volume(closed.delivered_af)} acre feet"),
                    ("ditch loss", f"{volume(closed.loss_af)} acre feet"),
                    ("unexplained", f"{volume(closed.report.unexplained_loss_af)} acre feet"),
                    ("accounts", str(len(closed.accounts))),
                    ("billed", str(closed.billed)),
                    ("record", ledger.provenance.value),
                ]
            )
        )
        if dry_run:
            click.echo("\nnothing written, this was a dry run")
            return
        numbers = save_run(connection, closed.bills, f"season {water_year}")
        recorded_at = datetime.combine(issued_day, datetime.min.time())
        for line in closed.report.lines:
            post(
                connection,
                recorded_at,
                EntryKind.DELIVERY,
                str(line.turnout),
                f"season {water_year}",
                volume_af=line.delivered_af,
            )
        for account in closed.bills.accounts:
            post(
                connection,
                recorded_at,
                EntryKind.ASSESSMENT,
                f"account {account}",
                f"season {water_year}",
                amount=closed.bill_for(account).total,
            )
        click.echo(f"\n{len(numbers)} bills written and posted to the journal")


def register(group: click.Group) -> None:
    """Hang the close command off the season group."""

    group.add_command(close)
