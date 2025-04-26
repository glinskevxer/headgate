"""The reservoir commands.

Building the reservoir, filling it, allocating what is in it, and drawing
against an account. The fill and the allocation are separate on purpose: the
pool fills all spring and the board decides in April what it is willing to
allocate, which is never quite the same number.
"""

from __future__ import annotations

import sqlite3
from decimal import Decimal

import click

from ..errors import NotFoundError, PolicyError
from ..ids import AccountNumber, DecreeNumber
from ..model.reservoir import PoolState, Reservoir
from ..storage.account import allocate
from ..store.repo_accounts import load_register
from ..store.repo_storage import (
    load_pool,
    load_reservoir,
    load_storage_book,
    save_pool,
    save_reservoir,
    save_storage_book,
)
from ..wateryear import parse_day, water_year_of
from .context import Context
from .render import Align, Column, field_list, render_table, volume, yes_no


@click.group()
def reservoir() -> None:
    """The reservoir, the pool and the storage accounts."""


@reservoir.command("build")
@click.option("--name", required=True, help="What the reservoir is called.")
@click.option("--decree", required=True, help="The storage right that fills it.")
@click.option("--capacity", required=True, help="Capacity in acre feet.")
@click.option("--dead-pool", default="0", show_default=True, help="Acre feet below the outlet.")
@click.pass_obj
def build(context: Context, name: str, decree: str, capacity: str, dead_pool: str) -> None:
    """Put a reservoir in the book."""

    built = Reservoir(
        name=name,
        decree=DecreeNumber.parse(decree),
        capacity_af=Decimal(capacity),
        dead_pool_af=Decimal(dead_pool),
    )
    with context.open_current() as connection:
        save_reservoir(connection, built)
        click.echo(
            f"{built.name} holds {volume(built.capacity_af)} acre feet, "
            f"{volume(built.usable_af)} of it usable"
        )


@reservoir.command("fill")
@click.option("--name", required=True, help="Which reservoir.")
@click.option("--on", "day", required=True, help="The day the water came in.")
@click.option("--inflow", required=True, help="Acre feet stored that day.")
@click.pass_obj
def fill(context: Context, name: str, day: str, inflow: str) -> None:
    """Store a day's inflow, spilling what will not fit."""

    when = parse_day(day)
    water_year = water_year_of(when)
    with context.open_current() as connection:
        pool = _pool_or_empty(connection, name, water_year)
        filled = pool.fill(Decimal(inflow), when)
        save_pool(connection, filled)
        click.echo(
            f"{name} holds {volume(filled.contents_af)} acre feet, "
            f"{filled.percent_full} percent full"
        )
        if filled.spilled_af > pool.spilled_af:
            click.echo(f"{volume(filled.spilled_af - pool.spilled_af)} acre feet spilled")


def _pool_or_empty(connection: sqlite3.Connection, name: str, water_year: int) -> PoolState:
    """The pool as it stands, or an empty one sitting on the dead pool.

    A year nobody has stored water in yet has no row, and the reservoir starts
    that year at whatever is below the outlet.
    """

    try:
        return load_pool(connection, name, water_year)
    except NotFoundError:
        found = load_reservoir(connection, name)
        return PoolState(reservoir=found, water_year=water_year, contents_af=found.dead_pool_af)


@reservoir.command("allocate")
@click.option("--name", required=True, help="Which reservoir.")
@click.option("--year", "water_year", required=True, type=int, help="Water year.")
@click.option("--on", "as_of", required=True, help="The day the shares are counted on.")
@click.pass_obj
def allocate_pool(context: Context, name: str, water_year: int, as_of: str) -> None:
    """Split the usable pool between the shareholders."""

    day = parse_day(as_of)
    with context.open_current() as connection:
        pool = load_pool(connection, name, water_year)
        register = load_register(connection)
        shares = {
            holder.number: register.shares_of(holder.number, day)
            for holder in register.accounts
            if register.shares_of(holder.number, day) > 0
        }
        if not shares:
            raise PolicyError("nobody held shares on that day")
        book = allocate(water_year, pool.usable_af, shares)
        save_storage_book(connection, name, book)
        click.echo(
            f"{volume(pool.usable_af)} acre feet allocated across {len(book.entries)} accounts"
        )


@reservoir.command("draw")
@click.option("--name", required=True, help="Which reservoir.")
@click.option("--year", "water_year", required=True, type=int, help="Water year.")
@click.option("--account", "account_number", required=True, help="Whose water it is.")
@click.option("--volume", "wanted", required=True, help="Acre feet to release.")
@click.pass_obj
def draw(context: Context, name: str, water_year: int, account_number: str, wanted: str) -> None:
    """Release water against one account's storage."""

    account = AccountNumber.parse(account_number)
    with context.open_current() as connection:
        book = load_storage_book(connection, name, water_year)
        drawn = book.release_to(account, Decimal(wanted))
        pool = load_pool(connection, name, water_year)
        save_pool(connection, pool.release(Decimal(wanted)))
        save_storage_book(connection, name, drawn)
        click.echo(
            f"account {account} has {volume(drawn.balance_of(account))} acre feet left in {name}"
        )


@reservoir.command("show")
@click.option("--name", required=True, help="Which reservoir.")
@click.option("--year", "water_year", required=True, type=int, help="Water year.")
@click.pass_obj
def show(context: Context, name: str, water_year: int) -> None:
    """The pool and the accounts behind it."""

    with context.open_current() as connection:
        pool = load_pool(connection, name, water_year)
        click.echo(
            field_list(
                [
                    ("reservoir", pool.reservoir.name),
                    ("water year", str(water_year)),
                    ("contents", f"{volume(pool.contents_af)} acre feet"),
                    ("usable", f"{volume(pool.usable_af)} acre feet"),
                    ("full", f"{pool.percent_full} percent"),
                    ("filled", f"{volume(pool.filled_af)} acre feet"),
                    ("spilled", f"{volume(pool.spilled_af)} acre feet"),
                    ("released", f"{volume(pool.released_af)} acre feet"),
                    ("fill done", yes_no(pool.fill_finished)),
                ]
            )
        )
        try:
            book = load_storage_book(connection, name, water_year)
        except NotFoundError:
            click.echo("\nnothing allocated yet")
            return
        click.echo()
        columns = [
            Column("account", Align.RIGHT),
            Column("shares", Align.RIGHT),
            Column("allocated", Align.RIGHT),
            Column("released", Align.RIGHT),
            Column("left", Align.RIGHT),
        ]
        rows = [
            [
                str(entry.account),
                f"{entry.shares}",
                volume(entry.allocated_af),
                volume(entry.released_af),
                volume(entry.balance_af),
            ]
            for entry in book.entries
        ]
        click.echo(render_table(columns, rows))


def register(group: click.Group) -> None:
    """Hang the reservoir commands off the main group."""

    group.add_command(reservoir)
