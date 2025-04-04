"""The well commands.

Drilling a well into the book, recording what it pumped, and asking the two
questions that matter in a call year: how much of that pumping has reached the
creek by now, and how much of it has been put back.

The depletion command is the one that surprises people. A well that stopped
pumping in August is still taking water out of the creek in October, and the
number it prints is the number the commissioner administers against.
"""

from __future__ import annotations

from decimal import Decimal

import click

from ..errors import PolicyError
from ..ids import DecreeNumber
from ..store.repo_wells import (
    load_well,
    load_wells,
    pumped_total,
    pumping_for,
    record_pumping,
    save_well,
)
from ..wells.augmentation import AugmentationPlan, ReplacementSource, SourceKind
from ..wells.depletion import Well, augmentation_owed, check_annual_limit, depletion_by_month
from .context import Context
from .render import Align, Column, field_list, plural, render_table, volume, yes_no

SOURCE_NAMES = [item.value.replace("_", "-") for item in SourceKind]


@click.group()
def well() -> None:
    """Supplemental wells and what they take out of the creek."""


@well.command("add")
@click.option("--id", "well_id", required=True, help="Well identifier.")
@click.option("--decree", required=True, help="The right it pumps under.")
@click.option("--distance", required=True, help="Feet from the stream.")
@click.option("--storativity", required=True, help="Aquifer storativity.")
@click.option("--transmissivity", required=True, help="Transmissivity in square feet a day.")
@click.option("--capacity", required=True, help="Pump capacity in gallons a minute.")
@click.option("--limit", default=None, help="Annual limit in acre feet, if the decree sets one.")
@click.pass_obj
def add(
    context: Context,
    well_id: str,
    decree: str,
    distance: str,
    storativity: str,
    transmissivity: str,
    capacity: str,
    limit: str | None,
) -> None:
    """Put a well in the book."""

    built = Well(
        well_id=well_id,
        decree=DecreeNumber.parse(decree),
        distance_to_stream_feet=Decimal(distance),
        storativity=Decimal(storativity),
        transmissivity_ft2_day=Decimal(transmissivity),
        capacity_gpm=Decimal(capacity),
        annual_limit_af=Decimal(limit) if limit is not None else None,
    )
    with context.open_current() as connection:
        save_well(connection, built)
        click.echo(
            f"well {built.well_id} added, depletion factor {built.factor_days} days, "
            f"administered as a diversion: {yes_no(built.is_close_to_the_stream)}"
        )


@well.command("pumped")
@click.option("--id", "well_id", required=True, help="Which well.")
@click.option("--year", "water_year", required=True, type=int, help="Water year.")
@click.option("--month", required=True, type=int, help="Month the meter covers.")
@click.option("--volume", "pumped_af", required=True, help="Acre feet pumped.")
@click.pass_obj
def pumped(context: Context, well_id: str, water_year: int, month: int, pumped_af: str) -> None:
    """Record a month's pumping off the meter."""

    with context.open_current() as connection:
        record_pumping(connection, well_id, water_year, month, Decimal(pumped_af))
        found = load_well(connection, well_id)
        total = pumped_total(connection, well_id, water_year)
        check_annual_limit(found, total)
        click.echo(f"well {well_id} has pumped {volume(total)} acre feet in {water_year}")


@well.command("depletion")
@click.option("--id", "well_id", required=True, help="Which well.")
@click.option("--year", "water_year", required=True, type=int, help="Water year.")
@click.option("--through", required=True, type=int, help="Month to work the depletion to.")
@click.option("--replaced", default="0", show_default=True, help="Acre feet already put back.")
@click.pass_obj
def depletion(context: Context, well_id: str, water_year: int, through: int, replaced: str) -> None:
    """How much of the pumping has reached the creek, and what is owed."""

    with context.open_current() as connection:
        records = list(pumping_for(connection, well_id, water_year))
        if not records:
            raise PolicyError(f"well {well_id} pumped nothing in {water_year}")
        found = load_well(connection, well_id)
        by_month = depletion_by_month(records, through)
        owed = augmentation_owed(records, through, Decimal(replaced))
        total = pumped_total(connection, well_id, water_year)
    click.echo(
        field_list(
            [
                ("well", well_id),
                ("factor", f"{found.factor_days} days"),
                ("pumped", f"{volume(total)} acre feet"),
                ("depleted", f"{volume(sum(by_month.values(), Decimal('0')))} acre feet"),
                ("replaced", f"{volume(Decimal(replaced))} acre feet"),
                ("owed", f"{volume(owed)} acre feet"),
            ]
        )
    )
    click.echo()
    columns = [
        Column("month", Align.RIGHT),
        Column("pumped", Align.RIGHT),
        Column("depleted", Align.RIGHT),
    ]
    pumping = {item.month: item.pumped_af for item in records}
    rows = [
        [str(month), volume(pumping.get(month, Decimal("0"))), volume(value)]
        for month, value in sorted(by_month.items())
    ]
    click.echo(render_table(columns, rows))


@well.command("cover")
@click.option("--id", "well_id", required=True, help="Which well.")
@click.option("--year", "water_year", required=True, type=int, help="Water year.")
@click.option("--through", required=True, type=int, help="Month to work the plan to.")
@click.option("--mile", required=True, help="River mile the depletion is felt at.")
@click.option(
    "--source",
    multiple=True,
    help="A source as name:mile:month=af,month=af, one for each replacement.",
)
@click.option(
    "--kind",
    type=click.Choice(SOURCE_NAMES),
    default="storage-release",
    show_default=True,
    help="What the sources are.",
)
@click.pass_obj
def cover(
    context: Context,
    well_id: str,
    water_year: int,
    through: int,
    mile: str,
    source: tuple[str, ...],
    kind: str,
) -> None:
    """Match a well's depletion against the water put back for it."""

    sources: list[ReplacementSource] = []
    for text in source:
        pieces = text.split(":")
        if len(pieces) != 3:
            raise PolicyError(f"{text!r} is not a source, write it as name:mile:month=af,month=af")
        monthly: dict[int, Decimal] = {}
        for pair in pieces[2].split(","):
            month, _, volume_af = pair.partition("=")
            if not volume_af:
                raise PolicyError(f"{pair!r} is not a month, write it as month=af")
            monthly[int(month)] = Decimal(volume_af)
        sources.append(
            ReplacementSource(
                name=pieces[0],
                kind=SourceKind(kind.replace("-", "_")),
                delivery_mile=Decimal(pieces[1]),
                monthly_af=monthly,
            )
        )
    with context.open_current() as connection:
        records = list(pumping_for(connection, well_id, water_year))
        if not records:
            raise PolicyError(f"well {well_id} pumped nothing in {water_year}")
    plan = AugmentationPlan(
        name=f"{well_id} {water_year}", depletion_mile=Decimal(mile), sources=tuple(sources)
    )
    matches = plan.match(records, through)
    columns = [
        Column("month", Align.RIGHT),
        Column("owed", Align.RIGHT),
        Column("replaced", Align.RIGHT),
        Column("short", Align.RIGHT),
    ]
    rows = [
        [str(item.month), volume(item.owed_af), volume(item.replaced_af), volume(item.shortfall_af)]
        for item in matches
    ]
    click.echo(render_table(columns, rows))
    short = plan.first_short_month(records, through)
    if short is None:
        click.echo(f"\nthe plan covers every month through {through}")
        return
    click.echo(
        f"\nshort {volume(plan.shortfall(records, through))} acre feet, first in month {short}"
    )
    if plan.out_of_place:
        click.echo(
            f"{plural(len(plan.out_of_place), 'source')} land below the depletion and do "
            "nothing for it"
        )


@well.command("list")
@click.pass_obj
def list_wells(context: Context) -> None:
    """The wells in the book, and how quickly each one reaches the creek."""

    with context.open_current() as connection:
        found = load_wells(connection)
        if not found:
            click.echo("no wells yet")
            return
        columns = [
            Column("well"),
            Column("decree"),
            Column("feet", Align.RIGHT),
            Column("factor", Align.RIGHT),
            Column("like a diversion"),
        ]
        rows = [
            [
                item.well_id,
                str(item.decree),
                f"{item.distance_to_stream_feet}",
                f"{item.factor_days}",
                yes_no(item.is_close_to_the_stream),
            ]
            for item in found
        ]
        click.echo(render_table(columns, rows))


def register(group: click.Group) -> None:
    """Hang the well commands off the main group."""

    group.add_command(well)
