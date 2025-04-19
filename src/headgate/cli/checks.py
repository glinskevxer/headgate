"""The check command.

One command the office can run before a season and after a restore. It reads
the book over, prints what is wrong with it, and exits non zero if anything it
found would stop the season, so it can go in a cron job and be believed.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import click

from ..store.audit import (
    Finding,
    audit,
    known_checks,
    problems,
    summarise,
)
from ..store.backup import back_up, restore, verify
from ..store.maintenance import analyse, measure, optimise, table_sizes, vacuum
from ..store.migrations import describe, pending
from ..wateryear import parse_day
from .context import Context
from .render import Align, Column, render_table


@click.command("check")
@click.option("--on", "as_of", default=None, help="The day to check against, default today.")
@click.option(
    "--warnings/--no-warnings",
    default=True,
    show_default=True,
    help="Print the warnings as well as the problems.",
)
@click.option("--list-checks", is_flag=True, help="Print what gets checked and stop.")
@click.pass_obj
def check(context: Context, as_of: str | None, warnings: bool, list_checks: bool) -> None:
    """Read the book over and say what is wrong with it."""

    if list_checks:
        for name in known_checks():
            click.echo(name)
        return
    day = parse_day(as_of) if as_of is not None else date.today()
    with context.open() as connection:
        waiting = pending(connection)
        if waiting:
            click.echo(f"schema: {len(waiting)} migrations have not been run")
            raise SystemExit(1)
        click.echo(f"schema: {describe(connection)}")
        found = audit(connection, day)
    if not found:
        click.echo(f"nothing wrong with the book on {day}")
        return
    shown = found if warnings else problems(found)
    click.echo(_table(shown))
    click.echo()
    click.echo(summarise(found))
    if problems(found):
        raise SystemExit(1)


def _table(findings: tuple[Finding, ...]) -> str:
    columns = [
        Column("severity"),
        Column("check"),
        Column("subject"),
        Column("what", Align.LEFT),
    ]
    rows = [[item.severity.value, item.check, item.subject, item.detail] for item in findings]
    return render_table(columns, rows)


@click.command("backup")
@click.argument("destination", type=click.Path(dir_okay=False, path_type=Path))
@click.pass_obj
def backup(context: Context, destination: Path) -> None:
    """Copy the book to another file, through SQLite rather than around it."""

    result = back_up(context.database.path, destination)
    click.echo(result.describe())


@click.command("verify")
@click.argument("path", type=click.Path(dir_okay=False, path_type=Path))
def verify_book(path: Path) -> None:
    """Say whether a file is a book this version can use."""

    sound, complaints = verify(path)
    if sound:
        click.echo(f"{path} is sound")
        return
    for complaint in complaints:
        click.echo(f"{path}: {complaint}")
    raise SystemExit(1)


@click.command("restore")
@click.argument("backup_path", type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.pass_obj
def restore_book(context: Context, backup_path: Path) -> None:
    """Put a backup back as the district book."""

    result = restore(backup_path, context.database.path)
    click.echo(f"restored to {result.describe()}")


@click.command("maintain")
@click.option("--vacuum", "run_vacuum", is_flag=True, help="Rebuild the file as well.")
@click.pass_obj
def maintain(context: Context, run_vacuum: bool) -> None:
    """Give the planner fresh statistics, and tidy the file if it is asked."""

    with context.open_current() as connection:
        size = measure(connection)
        analyse(connection)
        optimise(connection)
        tables = table_sizes(connection)
    click.echo(size.describe())
    for table, rows in list(tables.items())[:5]:
        click.echo(f"{table}: {rows} rows")
    if not run_vacuum:
        if size.is_worth_vacuuming:
            click.echo("\nthe file is worth vacuuming, run this again with --vacuum")
        return
    before = vacuum(context.database.path)
    click.echo(f"\nrebuilt, {before.bytes_free} bytes were free before it")


def register(group: click.Group) -> None:
    """Hang the check command off the main group."""

    group.add_command(check)
    group.add_command(backup)
    group.add_command(verify_book)
    group.add_command(restore_book)
    group.add_command(maintain)
