"""The check command.

One command the office can run before a season and after a restore. It reads
the book over, prints what is wrong with it, and exits non zero if anything it
found would stop the season, so it can go in a cron job and be believed.
"""

from __future__ import annotations

from datetime import date

import click

from ..store.audit import (
    Finding,
    audit,
    known_checks,
    problems,
    summarise,
)
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


def register(group: click.Group) -> None:
    """Hang the check command off the main group."""

    group.add_command(check)
