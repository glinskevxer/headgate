"""Restating a season after a device turns out to have been reading wrong.

The command does what the office does by hand and gets wrong: work out what the
turnout should have been credited with, rebuild the bill for whoever is behind
that gate, reverse the old bill, issue the new one, and put both in the
journal. Nothing is edited. The season file ends up holding three documents and
the arithmetic between them.

The board's threshold applies here as it does anywhere else. A restatement over
it needs the board, and the command says so rather than quietly writing it.
"""

from __future__ import annotations

import sqlite3
from datetime import date, datetime
from decimal import Decimal

import click

from ..assessment.billing import Bill, ChargeKind, bill_account
from ..assessment.repost import restate as restate_bill
from ..audit.journal import EntryKind
from ..errors import PolicyError
from ..ids import AccountNumber, DeviceTag
from ..measure.recalibration import Rerating, material, restate
from ..store.assemble import turnout_owners
from ..store.repo_bills import bills_for_account, save_bill
from ..store.repo_devices import load_device
from ..store.repo_journal import post
from ..store.repo_readings import load_series_within
from ..store.repo_schedule import load_schedule
from ..store.repo_season import load_season
from ..wateryear import parse_day
from .context import Context
from .render import field_list, volume


@click.command("restate")
@click.option("--year", "water_year", required=True, type=int, help="Season to restate.")
@click.option("--device", "device_tag", required=True, help="The device that read wrong.")
@click.option("--offset", required=True, help="The staff offset it should have had, in feet.")
@click.option("--found", required=True, help="The day the check found it.")
@click.option("--by", "found_by", required=True, help="Who found it.")
@click.option("--reason", required=True, help="What was wrong with it.")
@click.option("--issued", default=None, help="The day the new bill goes out.")
@click.option("--board-approved", is_flag=True, help="The board has approved the change.")
@click.option("--dry-run", is_flag=True, help="Work the numbers and write nothing.")
@click.pass_obj
def restate_season(
    context: Context,
    water_year: int,
    device_tag: str,
    offset: str,
    found: str,
    found_by: str,
    reason: str,
    issued: str | None,
    board_approved: bool,
    dry_run: bool,
) -> None:
    """Restate a season after a device is re-rated."""

    issued_day = parse_day(issued) if issued is not None else date.today()
    with context.open_current() as connection:
        season = load_season(connection, water_year)
        span = season.as_span()
        device = load_device(connection, DeviceTag.parse(device_tag))
        if device.turnout is None:
            raise PolicyError(f"device {device.tag} is on a ditch, not a turnout")
        rerating = Rerating(
            device=device,
            corrected_offset_feet=Decimal(offset),
            found_on=parse_day(found),
            found_by=found_by,
            reason=reason,
        )
        series = load_series_within(connection, device.tag, span)
        found_change = restate(rerating, device.turnout, series, span)
        click.echo(
            field_list(
                [
                    ("turnout", str(device.turnout)),
                    ("was", f"{volume(found_change.before.total_af)} acre feet"),
                    ("should be", f"{volume(found_change.after.total_af)} acre feet"),
                    ("change", f"{volume(found_change.change_af)} acre feet"),
                    ("percent", f"{found_change.percent_change}"),
                ]
            )
        )
        if not material(found_change):
            click.echo("\nthe change is under an acre foot, which is not worth restating")
            return
        owners = turnout_owners(connection, season.opened)
        behind = owners.get(device.turnout)
        if not behind:
            raise PolicyError(f"no account stands behind {device.turnout}")
        if len(behind) > 1:
            raise PolicyError(
                f"turnout {device.turnout} is shared, so the restatement has to be worked by hand"
            )
        account = next(iter(behind))
        shares = behind[account]
        schedule = load_schedule(connection, water_year)
        original = _original_bill(connection, account, water_year)
        delivered = _quantity_on(original, ChargeKind.WATER)
        replacement = bill_account(
            account=account,
            water_year=water_year,
            issued_on=issued_day,
            schedule=schedule,
            shares=shares,
            delivered_af=delivered + found_change.change_af,
            loss_af=_quantity_on(original, ChargeKind.DITCH_LOSS),
        )
        restatement = restate_bill(
            original, replacement, reason, issued_day, board_approved=board_approved
        )
        click.echo(
            field_list(
                [
                    ("account", str(account)),
                    ("billed", str(original.total)),
                    ("now", str(replacement.total)),
                    ("adjustment", str(restatement.adjustment)),
                    ("board", "approved" if board_approved else "not needed"),
                ]
            )
        )
        if dry_run:
            click.echo("\nnothing written, this was a dry run")
            return
        reversal_id = save_bill(connection, restatement.reversal, f"restatement of {water_year}")
        save_bill(
            connection,
            restatement.replacement,
            f"restatement of {water_year}",
            reverses=reversal_id,
        )
        recorded_at = datetime.combine(issued_day, datetime.min.time())
        post(
            connection,
            recorded_at,
            EntryKind.CALIBRATION,
            str(device.tag),
            reason,
            volume_af=found_change.change_af,
        )
        post(
            connection,
            recorded_at,
            EntryKind.RESTATEMENT,
            f"account {account}",
            f"season {water_year}",
            amount=restatement.adjustment,
        )
        click.echo("\nthe reversal and the new bill are written and posted")


def _original_bill(connection: sqlite3.Connection, account: AccountNumber, water_year: int) -> Bill:
    """The bill the season was closed on, which the restatement answers."""

    bills = [
        item for item in bills_for_account(connection, account) if item.water_year == water_year
    ]
    if not bills:
        raise PolicyError(f"account {account} was never billed for {water_year}")
    return bills[0]


def _quantity_on(bill: Bill, kind: ChargeKind) -> Decimal:
    """The water a line was measured against, or nothing if it has no line."""

    line = bill.line_for(kind)
    return line.quantity if line is not None else Decimal("0")


def register(group: click.Group) -> None:
    """Hang the restate command off the season group."""

    group.add_command(restate_season)
