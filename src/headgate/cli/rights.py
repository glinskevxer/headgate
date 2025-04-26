"""The decree and stream commands.

Typing the decrees into a new book, and describing the creek they are
administered on. Both are done once and then argued about for years, so the
commands print back what they wrote and the list prints the ladder in the order
the commissioner walks it.
"""

from __future__ import annotations

from decimal import Decimal

import click

from ..errors import PolicyError, ValidationError
from ..ids import DecreeNumber, DitchCode
from ..model.right import Priority, RightKind, RightStatus, WaterRight
from ..model.stream import Reach, Stream
from ..store.repo_ditch import load_stream, save_stream
from ..store.repo_rights import load_ladder, load_right, save_right, set_status
from ..wateryear import parse_day
from .context import Context
from .render import Align, Column, field_list, rate, render_table

KIND_NAMES = [item.value.replace("_", "-") for item in RightKind]
STATUS_NAMES = [item.value for item in RightStatus]


@click.group()
def right() -> None:
    """Decreed water rights."""


@right.command("add")
@click.option("--decree", required=True, help="Decree number, such as CDA-1920-4.")
@click.option("--owner", required=True, help="Whose right it is.")
@click.option(
    "--kind",
    default="direct-flow",
    type=click.Choice(KIND_NAMES),
    show_default=True,
    help="What the decree entitles them to.",
)
@click.option("--appropriated", required=True, help="The appropriation date.")
@click.option("--sequence", required=True, type=int, help="Place in the decree book.")
@click.option("--mile", required=True, help="River mile of the point of diversion.")
@click.option("--rate", "rate_cfs", default=None, help="Decreed rate in cfs.")
@click.option("--volume", default=None, help="Decreed volume in acre feet.")
@click.option("--ditch", "ditch_code", default=None, help="The ditch it is decreed to.")
@click.pass_obj
def add(
    context: Context,
    decree: str,
    owner: str,
    kind: str,
    appropriated: str,
    sequence: int,
    mile: str,
    rate_cfs: str | None,
    volume: str | None,
    ditch_code: str | None,
) -> None:
    """Write a decreed right into the book."""

    number = DecreeNumber.parse(decree)
    built = WaterRight(
        decree=number,
        owner=owner,
        kind=RightKind(kind.replace("-", "_")),
        priority=Priority(parse_day(appropriated), number.adjudication_year, sequence),
        diversion_mile=Decimal(mile),
        rate_cfs=Decimal(rate_cfs) if rate_cfs is not None else None,
        volume_af=Decimal(volume) if volume is not None else None,
        ditch=DitchCode.parse(ditch_code) if ditch_code is not None else None,
    )
    with context.open_current() as connection:
        save_right(connection, built)
        click.echo(f"{built.decree} decreed to {built.owner}, priority {built.priority.describe()}")


@right.command("abandon")
@click.argument("decree")
@click.option(
    "--status",
    type=click.Choice(STATUS_NAMES),
    default="abandoned",
    show_default=True,
    help="What the court made of it.",
)
@click.pass_obj
def abandon(context: Context, decree: str, status: str) -> None:
    """Change a right's standing with the court."""

    with context.open_current() as connection:
        changed = set_status(connection, DecreeNumber.parse(decree), RightStatus(status))
        click.echo(f"{changed.decree} is now {changed.status.value}")


@right.command("list")
@click.option("--active", "only_active", is_flag=True, help="Leave off the dead ones.")
@click.pass_obj
def list_rights(context: Context, only_active: bool) -> None:
    """The ladder, most senior first."""

    with context.open_current() as connection:
        ladder = load_ladder(connection)
    if only_active:
        ladder = [item for item in ladder if item.is_active]
    if not ladder:
        click.echo("no decrees yet")
        return
    columns = [
        Column("decree"),
        Column("priority"),
        Column("owner"),
        Column("kind"),
        Column("rate", Align.RIGHT),
        Column("mile", Align.RIGHT),
        Column("status"),
    ]
    rows = [
        [
            str(item.decree),
            item.priority.appropriation_date.isoformat(),
            item.owner,
            item.kind.value,
            rate(item.rate_cfs),
            f"{item.diversion_mile}",
            item.status.value,
        ]
        for item in ladder
    ]
    click.echo(render_table(columns, rows))


@right.command("show")
@click.argument("decree")
@click.pass_obj
def show(context: Context, decree: str) -> None:
    """One decree, as the book has it."""

    with context.open_current() as connection:
        found = load_right(connection, DecreeNumber.parse(decree))
    click.echo(
        field_list(
            [
                ("decree", str(found.decree)),
                ("owner", found.owner),
                ("kind", found.kind.value),
                ("priority", found.priority.describe()),
                ("rate", f"{rate(found.rate_cfs)} cfs"),
                ("volume", f"{found.volume_af}" if found.volume_af is not None else "-"),
                ("mile", f"{found.diversion_mile}"),
                ("ditch", str(found.ditch) if found.ditch is not None else "-"),
                ("status", found.status.value),
                ("may call", "yes" if found.can_be_called else "no"),
            ]
        )
    )


@click.group()
def stream() -> None:
    """The creek the district diverts from."""


@stream.command("reach")
@click.option("--name", required=True, help="The stream's name.")
@click.option("--code", required=True, help="Reach code, such as R1.")
@click.option("--label", required=True, help="What the reach is called.")
@click.option("--head", required=True, help="River mile at the top of the reach.")
@click.option("--toe", required=True, help="River mile at the bottom.")
@click.option("--velocity", default="2", show_default=True, help="Mean velocity in feet a second.")
@click.option("--loss", default="0.01", show_default=True, help="Loss as a fraction a mile.")
@click.pass_obj
def add_reach(
    context: Context,
    name: str,
    code: str,
    label: str,
    head: str,
    toe: str,
    velocity: str,
    loss: str,
) -> None:
    """Add a reach to the stream, head to toe."""

    reach = Reach(
        code=code.upper(),
        name=label,
        head_mile=Decimal(head),
        toe_mile=Decimal(toe),
        mean_velocity_fps=Decimal(velocity),
        loss_fraction_per_mile=Decimal(loss),
    )
    with context.open_current() as connection:
        try:
            existing = load_stream(connection, name).reaches
        except ValidationError:
            existing = ()
        reaches = tuple(sorted((*existing, reach), key=lambda item: -item.head_mile))
        save_stream(connection, Stream(name=name, reaches=reaches))
        click.echo(
            f"reach {reach.code} added, mile {reach.head_mile} to {reach.toe_mile}, "
            f"{reach.length_miles} miles"
        )


@stream.command("show")
@click.option("--name", required=True, help="The stream's name.")
@click.pass_obj
def show_stream(context: Context, name: str) -> None:
    """The creek, reach by reach."""

    with context.open_current() as connection:
        found = load_stream(connection, name)
    if not found.reaches:
        raise PolicyError(f"{name} has no reaches in the book yet")
    columns = [
        Column("reach"),
        Column("name"),
        Column("head", Align.RIGHT),
        Column("toe", Align.RIGHT),
        Column("velocity", Align.RIGHT),
        Column("loss", Align.RIGHT),
    ]
    rows = [
        [
            item.code,
            item.name,
            f"{item.head_mile}",
            f"{item.toe_mile}",
            f"{item.mean_velocity_fps}",
            f"{item.loss_fraction_per_mile}",
        ]
        for item in found.reaches
    ]
    click.echo(render_table(columns, rows))
    click.echo(f"\n{found.name} runs from mile {found.head_mile} to {found.toe_mile}")


def register_commands(group: click.Group) -> None:
    """Hang the decree and stream commands off the main group."""

    group.add_command(right)
    group.add_command(stream)
