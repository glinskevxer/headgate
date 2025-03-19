"""The allotment commands.

Setting what a share is worth in a rationed year, revising it when the creek
proves the forecast wrong, and posting deliveries against it. The revise
command carries the rule about raising it late, which is the one the board
argues with every August.
"""

from __future__ import annotations

from decimal import Decimal

import click

from ..duty.allotment import allot
from ..errors import PolicyError
from ..ids import AccountNumber
from ..store.assemble import shares_by_account
from ..store.repo_allotment import (
    current_allotment,
    load_ledger,
    revisions,
    save_ledger,
    set_allotment,
    used_by,
)
from ..store.repo_season import load_season
from ..wateryear import parse_day
from .context import Context
from .render import Align, Column, field_list, render_table, volume, yes_no


@click.group()
def allotment() -> None:
    """What a share is worth in a rationed year."""


@allotment.command("set")
@click.option("--year", "water_year", required=True, type=int, help="Water year.")
@click.option("--available", required=True, help="Acre feet the district will hand out.")
@click.option("--basis", required=True, help="What the number was worked out from.")
@click.option("--on", "set_on", required=True, help="The day the board set it.")
@click.option("--duty", default=None, help="Cap on acre feet a share, if there is one.")
@click.pass_obj
def set_it(
    context: Context,
    water_year: int,
    available: str,
    basis: str,
    set_on: str,
    duty: str | None,
) -> None:
    """Work a supply down to acre feet a share and write it."""

    with context.open_current() as connection:
        season = load_season(connection, water_year)
        shares = {
            account: value
            for account, value in shares_by_account(connection, season.opened).items()
            if value > 0
        }
        if not shares:
            raise PolicyError("nobody held shares when the season opened")
        ledger = allot(
            water_year,
            Decimal(available),
            shares,
            parse_day(set_on),
            basis,
            Decimal(duty) if duty is not None else None,
        )
        set_allotment(connection, ledger.allotment)
        save_ledger(connection, ledger)
        click.echo(
            f"{water_year} allotment set at {volume(ledger.allotment.af_per_share)} acre feet "
            f"a share across {len(ledger.uses)} accounts"
        )


@allotment.command("revise")
@click.option("--year", "water_year", required=True, type=int, help="Water year.")
@click.option("--per-share", required=True, help="The new acre feet a share.")
@click.option("--on", "revised_on", required=True, help="The day the board revised it.")
@click.option("--basis", required=True, help="Why it changed.")
@click.pass_obj
def revise(context: Context, water_year: int, per_share: str, revised_on: str, basis: str) -> None:
    """Raise or cut the allotment, within the rule about raising it late."""

    with context.open_current() as connection:
        standing = current_allotment(connection, water_year)
        revised = standing.revise(Decimal(per_share), parse_day(revised_on), basis)
        set_allotment(connection, revised)
        click.echo(
            f"{water_year} allotment revised to {volume(revised.af_per_share)} acre feet a "
            f"share, revision {revised.revision}"
        )


@allotment.command("take")
@click.option("--year", "water_year", required=True, type=int, help="Water year.")
@click.option("--account", "account_number", required=True, help="Whose water.")
@click.option("--volume", "volume_af", required=True, help="Acre feet delivered.")
@click.pass_obj
def take(context: Context, water_year: int, account_number: str, volume_af: str) -> None:
    """Post a delivery against an account's allotment."""

    account = AccountNumber.parse(account_number)
    with context.open_current() as connection:
        ledger = load_ledger(connection, water_year).take(account, Decimal(volume_af))
        save_ledger(connection, ledger)
        click.echo(
            f"account {account} has {volume(ledger.remaining_af(account))} acre feet of its "
            f"{water_year} allotment left"
        )


@allotment.command("show")
@click.option("--year", "water_year", required=True, type=int, help="Water year.")
@click.option("--account", "account_number", default=None, help="One account only.")
@click.pass_obj
def show(context: Context, water_year: int, account_number: str | None) -> None:
    """The allotment as it stands, and what everybody has left."""

    with context.open_current() as connection:
        ledger = load_ledger(connection, water_year)
        history = revisions(connection, water_year)
        if account_number is not None:
            account = AccountNumber.parse(account_number)
            click.echo(
                field_list(
                    [
                        ("account", str(account)),
                        ("shares", f"{ledger.use_for(account).shares}"),
                        ("allowed", f"{volume(ledger.allowed_af(account))} acre feet"),
                        ("used", f"{volume(used_by(connection, account, water_year))} acre feet"),
                        ("left", f"{volume(ledger.remaining_af(account))} acre feet"),
                        ("over", yes_no(ledger.is_over(account))),
                    ]
                )
            )
            return
    click.echo(
        field_list(
            [
                ("water year", str(water_year)),
                ("a share", f"{volume(ledger.allotment.af_per_share)} acre feet"),
                ("set on", ledger.allotment.set_on.isoformat()),
                ("basis", ledger.allotment.basis),
                ("revisions", str(len(history))),
            ]
        )
    )
    click.echo()
    columns = [
        Column("account", Align.RIGHT),
        Column("shares", Align.RIGHT),
        Column("allowed", Align.RIGHT),
        Column("used", Align.RIGHT),
        Column("left", Align.RIGHT),
    ]
    rows = [
        [
            str(use.account),
            f"{use.shares}",
            volume(ledger.allowed_af(use.account)),
            volume(use.used_af),
            volume(ledger.remaining_af(use.account)),
        ]
        for use in ledger.uses
    ]
    click.echo(render_table(columns, rows))
    if ledger.overdrawn:
        click.echo(f"\n{len(ledger.overdrawn)} accounts are over their allotment")


def register(group: click.Group) -> None:
    """Hang the allotment commands off the main group."""

    group.add_command(allotment)
