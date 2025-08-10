"""The transfer commands.

Filing, publishing, protesting and approving. The one that does real work is
approve: it will not let terms through that grant more than the study proved or
that quietly drop the ground the applicant offered to dry up, because those are
the two things that go wrong in a transfer file and both of them are found
years later by somebody else.
"""

from __future__ import annotations

import sqlite3
from decimal import Decimal

import click

from ..duty.hcu import HistoricalUse, YearFinding, analyse
from ..errors import PolicyError
from ..ids import DecreeNumber, TurnoutCode
from ..store.assemble import consumptive_use_records
from ..store.repo_transfers import (
    applications_on,
    approved_volume_on,
    file_application,
    load_application,
    open_applications,
    save_application,
)
from ..transfer.application import (
    TransferApplication,
    TransferKind,
    terms_for,
)
from ..wateryear import parse_day
from .context import Context
from .render import Align, Column, field_list, render_table, volume

KIND_NAMES = [item.value.replace("_", "-") for item in TransferKind]


def _kind(name: str) -> TransferKind:
    return TransferKind(name.replace("-", "_"))


def _study(proved: str) -> HistoricalUse:
    average = Decimal(proved)
    return HistoricalUse(findings=(YearFinding(0, average, True, "as filed"),), average_af=average)


@click.group()
def transfer() -> None:
    """Applications to change a right."""


@transfer.command("file")
@click.option("--number", required=True, help="Application number.")
@click.option("--decree", required=True, help="The right being changed.")
@click.option("--kind", required=True, type=click.Choice(KIND_NAMES), help="What changes.")
@click.option("--filed", required=True, help="The day it was filed.")
@click.option("--requested", required=True, help="Acre feet asked to be moved.")
@click.option("--proved", default=None, help="Acre feet the study proves, if it is known.")
@click.option("--study-turnout", default=None, help="Work the study off this turnout's record.")
@click.option("--study-years", default=None, help="Water years for the study, as first-last.")
@click.option("--from-turnout", default=None, help="Where the water comes off.")
@click.option("--to-turnout", default=None, help="Where it is going.")
@click.option("--dry-up", multiple=True, help="A parcel offered for dry up.")
@click.pass_obj
def file_transfer(
    context: Context,
    number: str,
    decree: str,
    kind: str,
    filed: str,
    requested: str,
    proved: str | None,
    study_turnout: str | None,
    study_years: str | None,
    from_turnout: str | None,
    to_turnout: str | None,
    dry_up: tuple[str, ...],
) -> None:
    """File an application against a right."""

    with context.open_current() as connection:
        if proved is not None:
            study = _study(proved)
        else:
            study = _study_from_record(connection, study_turnout, study_years)
        application = TransferApplication(
            number=number,
            decree=DecreeNumber.parse(decree),
            kind=_kind(kind),
            filed_on=parse_day(filed),
            requested_af=Decimal(requested),
            study=study,
            from_turnout=TurnoutCode.parse(from_turnout) if from_turnout is not None else None,
            to_turnout=TurnoutCode.parse(to_turnout) if to_turnout is not None else None,
            dry_up_parcels=tuple(dry_up),
        )
        file_application(connection, application)
        click.echo(
            f"application {application.number} filed to move "
            f"{volume(application.requested_af)} acre feet off {application.decree}, "
            f"against {volume(study.average_af)} proved"
        )


def _study_from_record(
    connection: sqlite3.Connection, turnout: str | None, years: str | None
) -> HistoricalUse:
    """Work the study off the delivery record rather than off a typed number.

    This is the whole point of keeping provenance on every reading. A year the
    turnout was measured all through counts; a year it was estimated does not,
    and the applicant does not get to choose which.
    """

    if turnout is None or years is None:
        raise PolicyError(
            "either say what the study proves or give a turnout and years to work it from"
        )
    first, _, last = years.partition("-")
    if not last:
        raise PolicyError(f"{years!r} is not a study period, write it as first-last")
    records = consumptive_use_records(
        connection, TurnoutCode.parse(turnout), range(int(first), int(last) + 1)
    )
    if not records:
        raise PolicyError(f"there is no delivery record for {turnout} in those years")
    return analyse(records, minimum_years=1)


@transfer.command("publish")
@click.argument("number")
@click.pass_obj
def publish(context: Context, number: str) -> None:
    """Publish an application for protest."""

    with context.open_current() as connection:
        published = load_application(connection, number).publish()
        save_application(connection, published)
        click.echo(f"application {number} published")


@transfer.command("protest")
@click.argument("number")
@click.option("--note", required=True, help="What the protest says.")
@click.pass_obj
def protest(context: Context, number: str, note: str) -> None:
    """Record a protest against a published application."""

    with context.open_current() as connection:
        protested = load_application(connection, number).protest(note)
        save_application(connection, protested)
        click.echo(f"application {number} protested")


@transfer.command("approve")
@click.argument("number")
@click.option("--approved", required=True, help="Acre feet the terms allow.")
@click.option("--consumed-share", required=True, help="Share of the delivery consumed.")
@click.option("--condition", multiple=True, help="A condition of the approval.")
@click.pass_obj
def approve(
    context: Context,
    number: str,
    approved: str,
    consumed_share: str,
    condition: tuple[str, ...],
) -> None:
    """Approve an application on terms."""

    with context.open_current() as connection:
        application = load_application(connection, number)
        terms = terms_for(application, Decimal(approved), Decimal(consumed_share), tuple(condition))
        decided = application.approve(terms)
        save_application(connection, decided)
        click.echo(
            field_list(
                [
                    ("application", decided.number),
                    ("decree", str(decided.decree)),
                    ("approved", f"{volume(terms.approved_af)} acre feet"),
                    ("return flow", f"{volume(terms.return_flow_af)} acre feet"),
                    ("dry up", ", ".join(terms.dry_up_parcels) or "none"),
                    ("conditions", str(len(terms.conditions))),
                ]
            )
        )


@transfer.command("deny")
@click.argument("number")
@click.option("--reason", required=True, help="Why it was denied.")
@click.pass_obj
def deny(context: Context, number: str, reason: str) -> None:
    """Deny an application."""

    with context.open_current() as connection:
        denied = load_application(connection, number).deny(reason)
        save_application(connection, denied)
        click.echo(f"application {number} denied: {reason}")


@transfer.command("list")
@click.option("--decree", default=None, help="Only applications against one right.")
@click.option("--open", "only_open", is_flag=True, help="Only the ones still moving.")
@click.pass_obj
def list_transfers(context: Context, decree: str | None, only_open: bool) -> None:
    """List the applications in the book."""

    with context.open_current() as connection:
        if decree is not None:
            applications = applications_on(connection, DecreeNumber.parse(decree))
        elif only_open:
            applications = open_applications(connection)
        else:
            applications = open_applications(connection)
        if not applications:
            click.echo("no applications")
            return
        columns = [
            Column("number"),
            Column("decree"),
            Column("kind"),
            Column("asked", Align.RIGHT),
            Column("proved", Align.RIGHT),
            Column("status"),
        ]
        rows = [
            [
                item.number,
                str(item.decree),
                item.kind.value,
                volume(item.requested_af),
                volume(item.study.average_af),
                item.status.value,
            ]
            for item in applications
        ]
        click.echo(render_table(columns, rows))
        if decree is not None:
            moved = approved_volume_on(connection, DecreeNumber.parse(decree))
            click.echo(f"\n{volume(moved)} acre feet already moved off {decree}")


def register(group: click.Group) -> None:
    """Hang the transfer commands off the main group."""

    group.add_command(transfer)
