"""The lease commands.

Offering, approving, delivering against and cancelling. The check that matters
is on the offer: a shareholder cannot lease out water he has already leased to
somebody else, and the command works that out from the book rather than taking
his word for it.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import click

from ..ids import AccountNumber
from ..lease.agreement import Lease, LeaseSource, check_available
from ..money import Money
from ..store.repo_accounts import load_account
from ..store.repo_leases import (
    leases_for,
    load_book,
    load_lease,
    net_leased,
    offer,
    save_lease,
)
from ..wateryear import parse_day
from .context import Context
from .render import Align, Column, field_list, render_table, volume

SOURCE_NAMES = [item.value for item in LeaseSource]


@click.group()
def lease() -> None:
    """Leases of this year's water."""


@lease.command("offer")
@click.option("--number", required=True, help="Lease number.")
@click.option("--year", "water_year", required=True, type=int, help="Water year.")
@click.option("--from", "lessor_number", required=True, help="Who is leasing it out.")
@click.option("--to", "lessee_number", required=True, help="Who is taking it.")
@click.option("--volume", "volume_af", required=True, help="Acre feet.")
@click.option("--price", required=True, help="Price an acre foot, in dollars.")
@click.option(
    "--source",
    type=click.Choice(SOURCE_NAMES),
    default="allotment",
    show_default=True,
    help="What is being leased.",
)
@click.option("--holding", required=True, help="What the lessor has this year, in acre feet.")
@click.option("--on", "offered_on", default=None, help="The day it was offered.")
@click.pass_obj
def offer_lease(
    context: Context,
    number: str,
    water_year: int,
    lessor_number: str,
    lessee_number: str,
    volume_af: str,
    price: str,
    source: str,
    holding: str,
    offered_on: str | None,
) -> None:
    """Offer a lease of this year's water."""

    lessor = AccountNumber.parse(lessor_number)
    lessee = AccountNumber.parse(lessee_number)
    written = Lease(
        number=number,
        water_year=water_year,
        lessor=lessor,
        lessee=lessee,
        source=LeaseSource(source),
        volume_af=Decimal(volume_af),
        price=Money.parse(price),
        offered_on=parse_day(offered_on) if offered_on is not None else date.today(),
    )
    with context.open_current() as connection:
        load_account(connection, lessor)
        load_account(connection, lessee)
        book = load_book(connection, water_year)
        left = check_available(book, lessor, Decimal(holding), written.volume_af)
        offer(connection, written)
        click.echo(
            f"lease {written.number} offered, {volume(written.volume_af)} acre feet at "
            f"{written.price} an acre foot, {volume(left)} left uncommitted"
        )


@lease.command("approve")
@click.argument("number")
@click.option("--note", default="", help="The board minute, or anything like it.")
@click.pass_obj
def approve(context: Context, number: str, note: str) -> None:
    """Approve a lease so it can deliver water."""

    with context.open_current() as connection:
        approved = load_lease(connection, number).approve(note)
        save_lease(connection, approved)
        click.echo(f"lease {number} approved")


@lease.command("deliver")
@click.argument("number")
@click.option("--volume", "volume_af", required=True, help="Acre feet delivered.")
@click.pass_obj
def deliver(context: Context, number: str, volume_af: str) -> None:
    """Post water against a lease."""

    with context.open_current() as connection:
        running = load_lease(connection, number).deliver(Decimal(volume_af))
        save_lease(connection, running)
        click.echo(
            f"lease {number} has delivered {volume(running.delivered_af)} of "
            f"{volume(running.volume_af)} acre feet, {running.status.value}"
        )


@lease.command("cancel")
@click.argument("number")
@click.option("--note", required=True, help="Why it was cancelled.")
@click.pass_obj
def cancel(context: Context, number: str, note: str) -> None:
    """Cancel a lease that has not delivered anything."""

    with context.open_current() as connection:
        cancelled = load_lease(connection, number).cancel(note)
        save_lease(connection, cancelled)
        click.echo(f"lease {number} cancelled")


@lease.command("list")
@click.option("--year", "water_year", required=True, type=int, help="Water year.")
@click.option("--account", "account_number", default=None, help="Only one account's leases.")
@click.pass_obj
def list_leases(context: Context, water_year: int, account_number: str | None) -> None:
    """The lease book for a year."""

    with context.open_current() as connection:
        if account_number is not None:
            account = AccountNumber.parse(account_number)
            leases = leases_for(connection, account, water_year)
            net = net_leased(connection, account, water_year)
        else:
            leases = load_book(connection, water_year).leases
            net = Decimal("0")
        if not leases:
            click.echo(f"no leases in {water_year}")
            return
        columns = [
            Column("number"),
            Column("from", Align.RIGHT),
            Column("to", Align.RIGHT),
            Column("acre feet", Align.RIGHT),
            Column("delivered", Align.RIGHT),
            Column("status"),
        ]
        rows = [
            [
                item.number,
                str(item.lessor),
                str(item.lessee),
                volume(item.volume_af),
                volume(item.delivered_af),
                item.status.value,
            ]
            for item in leases
        ]
        click.echo(render_table(columns, rows))
        if account_number is not None:
            click.echo()
            click.echo(field_list([("net", f"{volume(net)} acre feet in {water_year}")]))


def register(group: click.Group) -> None:
    """Hang the lease commands off the main group."""

    group.add_command(lease)
