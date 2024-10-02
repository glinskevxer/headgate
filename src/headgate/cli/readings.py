"""The reading commands, including the import the riders actually use.

A rider comes back with a book full of numbers and nobody is going to type them
one at a time. The import takes the file the field tablet writes, checks every
row before it writes any of them, and refuses the whole file if one row is
wrong. A half loaded file is worse than no file, because the second attempt
then trips over the rows that did land.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path

import click

from ..errors import PolicyError, ValidationError
from ..ids import DeviceTag
from ..measure.quality import rate_reading
from ..model.reading import ReadingMethod, StaffReading
from ..store.repo_devices import load_device
from ..store.repo_readings import count_readings, load_series, save_reading
from ..wateryear import parse_instant
from .context import Context
from .render import Align, Column, rate, render_table, truncate

REQUIRED_COLUMNS = ("device", "taken_at", "observer")


@dataclass(frozen=True, slots=True)
class ImportRow:
    """One line of an import file, after it has been read."""

    line: int
    reading: StaffReading


def _decimal(value: str | None, column: str, line: int) -> Decimal | None:
    if value is None or not value.strip():
        return None
    try:
        return Decimal(value.strip())
    except InvalidOperation as exc:
        raise ValidationError(f"line {line}: {column} is {value!r}, which is not a number") from exc


def read_rows(path: Path) -> list[ImportRow]:
    """Read a whole import file, or raise on the first row that is wrong."""

    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames is None:
            raise ValidationError(f"{path} has no header row")
        missing = [name for name in REQUIRED_COLUMNS if name not in reader.fieldnames]
        if missing:
            raise ValidationError(f"{path} has no {missing[0]} column")
        rows: list[ImportRow] = []
        for line, record in enumerate(reader, start=2):
            method = ReadingMethod((record.get("method") or "staff").strip())
            rows.append(
                ImportRow(
                    line=line,
                    reading=StaffReading(
                        device=DeviceTag.parse(record["device"]),
                        taken_at=parse_instant(record["taken_at"]),
                        observer=record["observer"],
                        method=method,
                        head_feet=_decimal(record.get("head"), "head", line),
                        tail_feet=_decimal(record.get("tail"), "tail", line),
                        meter_total_af=_decimal(record.get("total"), "total", line),
                        note=(record.get("note") or "").strip(),
                    ),
                )
            )
    if not rows:
        raise PolicyError(f"{path} has a header and no readings")
    return rows


@click.group()
def reading() -> None:
    """Staff readings and meter totals."""


@reading.command("add")
@click.option("--device", "device_tag", required=True, help="Device tag.")
@click.option("--at", "taken_at", required=True, help="When it was read.")
@click.option("--by", "observer", required=True, help="Who read it.")
@click.option("--head", default=None, help="Gauge height in feet.")
@click.option("--tail", default=None, help="Tailwater in feet, for a flume.")
@click.option("--total", default=None, help="Meter total in acre feet.")
@click.option("--note", default="", help="Anything worth keeping with the reading.")
@click.pass_obj
def add(
    context: Context,
    device_tag: str,
    taken_at: str,
    observer: str,
    head: str | None,
    tail: str | None,
    total: str | None,
    note: str,
) -> None:
    """Write one reading and say what it means."""

    tag = DeviceTag.parse(device_tag)
    method = ReadingMethod.METER_TOTAL if total is not None else ReadingMethod.STAFF
    taken = StaffReading(
        device=tag,
        taken_at=parse_instant(taken_at),
        observer=observer,
        method=method,
        head_feet=Decimal(head) if head is not None else None,
        tail_feet=Decimal(tail) if tail is not None else None,
        meter_total_af=Decimal(total) if total is not None else None,
        note=note,
    )
    with context.open_current() as connection:
        device = load_device(connection, tag)
        save_reading(connection, taken)
        rated = rate_reading(device, taken)
        click.echo(
            f"{tag} at {taken.taken_at:%Y-%m-%d %H:%M}: {rate(rated.rate_cfs)} cfs, "
            f"{rated.provenance.value}, {rated.reason}"
        )


@reading.command("list")
@click.argument("device_tag")
@click.pass_obj
def list_readings(context: Context, device_tag: str) -> None:
    """Every reading on one device, oldest first."""

    tag = DeviceTag.parse(device_tag)
    with context.open_current() as connection:
        device = load_device(connection, tag)
        series = load_series(connection, tag)
        if series.is_empty:
            click.echo(f"nobody has read {tag}")
            return
        columns = [
            Column("taken"),
            Column("head", Align.RIGHT),
            Column("rate", Align.RIGHT),
            Column("record"),
            Column("observer"),
            Column("note"),
        ]
        rows = []
        for item in series.readings:
            rated = rate_reading(device, item)
            rows.append(
                [
                    f"{item.taken_at:%Y-%m-%d %H:%M}",
                    f"{item.head_feet:.2f}" if item.head_feet is not None else "-",
                    rate(rated.rate_cfs),
                    rated.provenance.value,
                    item.observer,
                    truncate(item.note, 24),
                ]
            )
        click.echo(render_table(columns, rows))


@reading.command("import")
@click.argument("path", type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.option("--dry-run", is_flag=True, help="Check the file and write nothing.")
@click.pass_obj
def import_readings(context: Context, path: Path, dry_run: bool) -> None:
    """Load a file of readings, all of it or none of it."""

    rows = read_rows(path)
    with context.open_current() as connection:
        for row in rows:
            load_device(connection, row.reading.device)
        if dry_run:
            click.echo(f"{path} holds {len(rows)} readings and every one of them checks out")
            return
        before = count_readings(connection)
        for row in rows:
            save_reading(connection, row.reading)
        written = count_readings(connection) - before
        click.echo(f"{written} readings loaded from {path}")


def register(group: click.Group) -> None:
    """Hang the reading commands off the main group."""

    group.add_command(reading)
