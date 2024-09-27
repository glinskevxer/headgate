"""The device commands.

Installing a structure, calibrating it, and asking what is in the ditch. The
calibration command is the one that matters: a district that lets its checks
lapse turns a measured season into an estimated one, and the list command says
which devices are about to do that.
"""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

import click

from ..errors import PolicyError
from ..ids import DeviceTag, DitchCode, TurnoutCode
from ..model.device import Calibration, Device, DeviceKind
from ..rating.select import rating_for
from ..store.repo_devices import load_device, load_devices, save_device, uncalibrated_on
from ..wateryear import parse_day
from .context import Context
from .render import Align, Column, field_list, render_table, yes_no

KIND_NAMES = [item.value.replace("_", "-") for item in DeviceKind]
DEFAULT_CALIBRATION_MONTHS = 12


def _kind(name: str) -> DeviceKind:
    return DeviceKind(name.replace("-", "_"))


@click.group()
def device() -> None:
    """Structures, their staff gauges and their calibrations."""


@device.command("install")
@click.option("--tag", required=True, help="Device tag, such as WEIR-L2-14.")
@click.option("--kind", required=True, type=click.Choice(KIND_NAMES), help="What it is.")
@click.option("--installed", required=True, help="The day it went in.")
@click.option("--turnout", "turnout_code", default=None, help="Turnout it sits in.")
@click.option("--ditch", "ditch_code", default=None, help="Ditch it sits on.")
@click.option("--crest", default=None, help="Crest width in feet, for a weir.")
@click.option("--throat", default=None, help="Throat width in feet, for a flume or orifice.")
@click.option("--opening", default=None, help="Opening height in feet, for an orifice.")
@click.option("--contractions", default=0, type=int, help="End contractions on a weir.")
@click.pass_obj
def install(
    context: Context,
    tag: str,
    kind: str,
    installed: str,
    turnout_code: str | None,
    ditch_code: str | None,
    crest: str | None,
    throat: str | None,
    opening: str | None,
    contractions: int,
) -> None:
    """Put a structure in the ditch."""

    built = Device(
        tag=DeviceTag.parse(tag),
        kind=_kind(kind),
        installed=parse_day(installed),
        crest_width_feet=Decimal(crest) if crest is not None else None,
        throat_width_feet=Decimal(throat) if throat is not None else None,
        opening_height_feet=Decimal(opening) if opening is not None else None,
        end_contractions=contractions,
        turnout=TurnoutCode.parse(turnout_code) if turnout_code is not None else None,
        ditch=DitchCode.parse(ditch_code) if ditch_code is not None else None,
    )
    with context.open_current() as connection:
        save_device(connection, built)
        click.echo(f"{built.kind.value} {built.tag} installed at {built.site}")


@device.command("calibrate")
@click.option("--tag", required=True, help="Device tag.")
@click.option("--on", "performed", required=True, help="The day it was checked.")
@click.option("--by", "performed_by", required=True, help="Who checked it.")
@click.option("--offset", default="0", show_default=True, help="Staff offset in feet.")
@click.option(
    "--months",
    default=DEFAULT_CALIBRATION_MONTHS,
    show_default=True,
    help="How long the check stands.",
)
@click.option("--note", default="", help="Anything worth keeping with the check.")
@click.pass_obj
def calibrate(
    context: Context,
    tag: str,
    performed: str,
    performed_by: str,
    offset: str,
    months: int,
    note: str,
) -> None:
    """Record a field check against a current meter."""

    if months < 1:
        raise PolicyError("a calibration that expires the day it is done proves nothing")
    checked = parse_day(performed)
    expires = checked + timedelta(days=30 * months)
    with context.open_current() as connection:
        found = load_device(connection, DeviceTag.parse(tag))
        updated = found.with_calibration(
            Calibration(
                performed=checked,
                performed_by=performed_by,
                expires=expires,
                staff_offset_feet=Decimal(offset),
                note=note,
            )
        )
        save_device(connection, updated)
        click.echo(f"{found.tag} calibrated {checked}, stands until {expires}")


@device.command("list")
@click.option("--on", "as_of", default=None, help="The day to report as of.")
@click.pass_obj
def list_devices(context: Context, as_of: str | None) -> None:
    """List the devices and whether their calibration still stands."""

    day = parse_day(as_of) if as_of is not None else date.today()
    with context.open_current() as connection:
        devices = load_devices(connection)
        if not devices:
            click.echo("nothing installed yet")
            return
        columns = [
            Column("tag"),
            Column("kind"),
            Column("site"),
            Column("in service"),
            Column("calibrated"),
            Column("offset", Align.RIGHT),
        ]
        rows = [
            [
                str(item.tag),
                item.kind.value,
                item.site,
                yes_no(item.in_service_on(day)),
                yes_no(item.is_calibrated_on(day)),
                f"{item.staff_offset_on(day):.3f}",
            ]
            for item in devices
        ]
        click.echo(render_table(columns, rows))


@device.command("lapsed")
@click.option("--on", "as_of", default=None, help="The day to check.")
@click.pass_obj
def lapsed(context: Context, as_of: str | None) -> None:
    """Devices in the ditch with no calibration standing."""

    day = parse_day(as_of) if as_of is not None else date.today()
    with context.open_current() as connection:
        found = uncalibrated_on(connection, day)
        if not found:
            click.echo(f"every device in the ditch was calibrated on {day}")
            return
        for item in found:
            click.echo(f"{item.tag} at {item.site} has no calibration standing on {day}")


@device.command("show")
@click.argument("tag")
@click.option("--on", "as_of", default=None, help="The day to read it against.")
@click.pass_obj
def show(context: Context, tag: str, as_of: str | None) -> None:
    """What a device is, and what rating it reads against."""

    day = parse_day(as_of) if as_of is not None else date.today()
    with context.open_current() as connection:
        found = load_device(connection, DeviceTag.parse(tag))
        pairs = [
            ("tag", str(found.tag)),
            ("kind", found.kind.value),
            ("site", found.site),
            ("installed", found.installed.isoformat()),
            ("in service", yes_no(found.in_service_on(day))),
            ("calibrated", yes_no(found.is_calibrated_on(day))),
            ("checks", str(len(found.calibrations))),
        ]
        if found.kind.is_rated_on_a_staff and found.in_service_on(day):
            pairs.append(("rating", rating_for(found, day).describe()))
        click.echo(field_list(pairs))


def register(group: click.Group) -> None:
    """Hang the device commands off the main group."""

    group.add_command(device)
