"""The headgate command.

Every subcommand takes the book from the group, so the path is given once. The
group itself does not open anything: a command that only prints its own help
should not touch a district's file at all.
"""

from __future__ import annotations

from pathlib import Path

import click

from .. import __version__
from ..errors import HeadgateError
from ..store.migrations import current_version, describe, migrate, pending
from ..units import MinersInchStandard
from . import allotment as allotment_commands
from . import calls as call_commands
from . import checks as check_commands
from . import devices as device_commands
from . import gages as gage_commands
from . import leases as lease_commands
from . import orders as order_commands
from . import readings as reading_commands
from . import reports as report_commands
from . import rights as right_commands
from . import rotation as rotation_commands
from . import setup as setup_commands
from . import storage as storage_commands
from . import transfers as transfer_commands
from .context import DEFAULT_BOOK, Context, district_name

STANDARD_NAMES = [item.name.lower() for item in MinersInchStandard]


class DistrictGroup(click.Group):
    """A group that reports a deliberate failure the way click reports its own.

    Without this a PolicyError leaves the command line with a traceback, which
    tells a ditch rider nothing and tells a shell script nothing either.
    """

    def invoke(self, ctx: click.Context) -> object:
        try:
            return super().invoke(ctx)
        except HeadgateError as exc:
            raise click.ClickException(str(exc)) from exc


@click.group(cls=DistrictGroup)
@click.option(
    "--book",
    type=click.Path(dir_okay=False, path_type=Path),
    default=DEFAULT_BOOK,
    envvar="HEADGATE_BOOK",
    show_default=True,
    help="The district book to work on.",
)
@click.option("--quiet", is_flag=True, help="Print only what was asked for.")
@click.version_option(__version__, prog_name="headgate")
@click.pass_context
def main(context: click.Context, book: Path, quiet: bool) -> None:
    """Water accounting for a ditch company."""

    context.obj = Context.at(book, quiet)


@main.command()
@click.option("--name", required=True, help="The district's name.")
@click.option("--state", "state_code", required=True, help="Two letter state code.")
@click.option("--stream", required=True, help="The stream the main canal heads on.")
@click.option(
    "--miners-inch",
    type=click.Choice(STANDARD_NAMES),
    default="colorado",
    show_default=True,
    help="Which statute the district converts miner's inches under.",
)
@click.pass_obj
def init(context: Context, name: str, state_code: str, stream: str, miners_inch: str) -> None:
    """Set up a new district book."""

    version = context.set_up(name, state_code.upper(), stream, miners_inch.upper())
    click.echo(f"{name} set up in {context.database.path} at schema version {version}")


@main.command()
@click.pass_obj
def migrate_book(context: Context) -> None:
    """Bring an existing book up to this version."""

    with context.open() as connection:
        waiting = pending(connection)
        if not waiting:
            click.echo(f"{context.database.path} is already {describe(connection)}")
            return
        applied = migrate(connection)
        click.echo(f"applied {len(applied)} migrations, now {describe(connection)}")


@main.command()
@click.pass_obj
def status(context: Context) -> None:
    """Say what book this is and where it stands."""

    with context.open() as connection:
        version = current_version(connection)
        if version == 0:
            click.echo(f"{context.database.path} has never been set up")
            return
        name = district_name(connection)
        click.echo(f"district: {name if name is not None else 'not written yet'}")
        click.echo(f"schema:   {describe(connection)}")
        click.echo(f"pending:  {len(pending(connection))}")


order_commands.register(main)
report_commands.register(main)
setup_commands.register_commands(main)
device_commands.register(main)
reading_commands.register(main)
storage_commands.register(main)
check_commands.register(main)
transfer_commands.register(main)
call_commands.register_commands(main)
right_commands.register_commands(main)
lease_commands.register(main)
gage_commands.register(main)
rotation_commands.register(main)
allotment_commands.register(main)


def run() -> int:
    """Entry point that turns a deliberate failure into an exit status."""

    try:
        main.main(standalone_mode=False)
    except click.ClickException as exc:
        exc.show()
        return exc.exit_code
    except click.Abort:
        click.echo("headgate: stopped", err=True)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
