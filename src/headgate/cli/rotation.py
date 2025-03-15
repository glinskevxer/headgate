"""The rotation commands.

Building a cycle from the shares behind each turnout, printing it, and telling
a rider when his gate comes round again. Building it twice replaces the year's
plan, which is what happens every time the creek drops and the commissioner
shortens the cycle.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

import click

from ..errors import PolicyError
from ..ids import TurnoutCode
from ..rotation.build import Turn, build_cycle, repeat_cycle
from ..rotation.plan import check_plan
from ..store.assemble import shares_by_turnout
from ..store.repo_ditch import load_system
from ..store.repo_rotation import (
    count_windows,
    hours_for,
    load_plan,
    next_window,
    running_at,
    save_plan,
)
from ..store.repo_season import load_season
from ..wateryear import parse_instant
from .context import Context
from .render import Align, Column, field_list, hours, rate, render_table


@click.group()
def rotation() -> None:
    """Taking turns when there is not enough water to go round."""


@rotation.command("build")
@click.option("--year", "water_year", required=True, type=int, help="Water year.")
@click.option("--start", required=True, help="When the first set starts.")
@click.option("--flow", required=True, help="What the lateral has to hand out, in cfs.")
@click.option("--cycle-hours", default="48", show_default=True, help="Hours in one cycle.")
@click.option("--cycles", default=1, show_default=True, help="How many cycles to lay out.")
@click.option("--curtailed", multiple=True, help="A turnout the commissioner has shut.")
@click.pass_obj
def build(
    context: Context,
    water_year: int,
    start: str,
    flow: str,
    cycle_hours: str,
    cycles: int,
    curtailed: tuple[str, ...],
) -> None:
    """Lay a rotation out from the shares behind each turnout."""

    when = parse_instant(start)
    shut = tuple(TurnoutCode.parse(item) for item in curtailed)
    with context.open_current() as connection:
        season = load_season(connection, water_year)
        system = load_system(connection)
        shares = shares_by_turnout(connection, season.opened)
        if not shares:
            raise PolicyError("no turnout has shares behind it, so there is nothing to rotate")
        turns = [
            Turn(turnout=code, shares=value)
            for code, value in sorted(shares.items(), key=lambda item: str(item[0]))
        ]
        if cycles == 1:
            cycle = build_cycle(
                system, water_year, turns, Decimal(flow), when, Decimal(cycle_hours), shut
            )
            plan = cycle.plan
            skipped = cycle.skipped
            short = cycle.short_set
        else:
            plan = repeat_cycle(
                system, water_year, turns, Decimal(flow), when, Decimal(cycle_hours), cycles, shut
            )
            skipped = shut
            short = ()
        check_plan(plan, system, season)
        save_plan(connection, plan)
    click.echo(
        field_list(
            [
                ("water year", str(water_year)),
                ("windows", str(len(plan.windows))),
                ("turnouts", str(len(plan.turnouts))),
                ("skipped", ", ".join(str(item) for item in skipped) or "none"),
                ("too short", ", ".join(str(item) for item in short) or "none"),
            ]
        )
    )


@rotation.command("show")
@click.option("--year", "water_year", required=True, type=int, help="Water year.")
@click.pass_obj
def show(context: Context, water_year: int) -> None:
    """The rotation as it stands for a year."""

    with context.open_current() as connection:
        plan = load_plan(connection, water_year)
        if not plan.windows:
            click.echo(f"no rotation has been laid out for {water_year}")
            return
        columns = [
            Column("turnout"),
            Column("from"),
            Column("to"),
            Column("rate", Align.RIGHT),
            Column("hours", Align.RIGHT),
        ]
        rows = [
            [
                str(item.turnout),
                f"{item.span.start:%Y-%m-%d %H:%M}",
                f"{item.span.end:%Y-%m-%d %H:%M}",
                rate(item.rate_cfs),
                hours(item.hours),
            ]
            for item in plan.windows
        ]
        click.echo(render_table(columns, rows))
        click.echo()
        for turnout in plan.turnouts:
            click.echo(f"{turnout}: {hours(hours_for(connection, turnout, water_year))} hours")


@rotation.command("next")
@click.option("--turnout", "turnout_code", required=True, help="Which gate.")
@click.option("--after", default=None, help="The moment to look forward from.")
@click.pass_obj
def next_turn(context: Context, turnout_code: str, after: str | None) -> None:
    """When a turnout comes round again."""

    moment = parse_instant(after) if after is not None else datetime.now()
    with context.open_current() as connection:
        window = next_window(connection, TurnoutCode.parse(turnout_code), moment)
    click.echo(
        f"{window.turnout} runs {window.span.start:%Y-%m-%d %H:%M} to "
        f"{window.span.end:%Y-%m-%d %H:%M} at {rate(window.rate_cfs)} cfs"
    )


@rotation.command("running")
@click.option("--at", "moment", default=None, help="The moment to look at.")
@click.pass_obj
def running(context: Context, moment: str | None) -> None:
    """What the rotation says should be running right now."""

    when = parse_instant(moment) if moment is not None else datetime.now()
    with context.open_current() as connection:
        windows = running_at(connection, when)
        planned = count_windows(connection, when.year)
    if not windows:
        click.echo(f"the rotation has nothing running at {when:%Y-%m-%d %H:%M}")
        return
    for window in windows:
        click.echo(
            f"{window.turnout} at {rate(window.rate_cfs)} cfs until "
            f"{window.span.end:%Y-%m-%d %H:%M}"
        )
    click.echo(f"\n{planned} windows in the year's plan")


def register(group: click.Group) -> None:
    """Hang the rotation commands off the main group."""

    group.add_command(rotation)
