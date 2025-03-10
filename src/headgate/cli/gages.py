"""The gage commands.

Putting a gage on the creek, loading the published record into the book, and
printing what the creek did over a span. The show command is the one the office
uses in August, and it prints the holes in the record before it prints the
total, because the total is worth less than the holes are.
"""

from __future__ import annotations

import csv
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation
from pathlib import Path

import click

from ..errors import PolicyError, ValidationError
from ..model.gage import DailyMean, RecordGrade
from ..model.stream import GagePoint
from ..store.repo_gage import (
    count_days,
    gages,
    load_gage,
    load_hydrograph,
    record_day,
    save_gage,
)
from ..wateryear import parse_day
from .context import Context
from .render import Align, Column, field_list, plural, rate, render_table, volume, yes_no

GRADE_NAMES = [item.value.replace("_", "-") for item in RecordGrade]


def _grade(name: str) -> RecordGrade:
    return RecordGrade(name.replace("-", "_"))


@click.group()
def gage() -> None:
    """Stream gages and what they recorded."""


@gage.command("add")
@click.option("--code", required=True, help="Gage code, such as SANP-1.")
@click.option("--name", required=True, help="What the gage is called.")
@click.option("--mile", required=True, help="River mile it sits at.")
@click.option("--datum", default="0", show_default=True, help="Datum elevation in feet.")
@click.pass_obj
def add(context: Context, code: str, name: str, mile: str, datum: str) -> None:
    """Put a gage on the creek."""

    point = GagePoint(
        code=code.upper(),
        name=name,
        mile=Decimal(mile),
        datum_elevation_feet=Decimal(datum),
    )
    with context.open_current() as connection:
        save_gage(connection, point)
        click.echo(f"gage {point.code} added at mile {point.mile}")


@gage.command("record")
@click.option("--code", required=True, help="Which gage.")
@click.option("--on", "day", required=True, help="The day.")
@click.option("--mean", "mean_cfs", required=True, help="Mean flow for the day, in cfs.")
@click.option(
    "--grade",
    type=click.Choice(GRADE_NAMES),
    default="measured",
    show_default=True,
    help="What the record is worth.",
)
@click.pass_obj
def record(context: Context, code: str, day: str, mean_cfs: str, grade: str) -> None:
    """Write one day of the gage record."""

    reading = DailyMean(day=parse_day(day), mean_cfs=Decimal(mean_cfs), grade=_grade(grade))
    with context.open_current() as connection:
        load_gage(connection, code.upper())
        record_day(connection, code.upper(), reading)
        click.echo(
            f"{code.upper()} on {reading.day}: {rate(reading.mean_cfs)} cfs, {reading.grade.value}"
        )


@gage.command("import")
@click.option("--code", required=True, help="Which gage.")
@click.argument("path", type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.pass_obj
def import_record(context: Context, code: str, path: Path) -> None:
    """Load a published record, all of it or none of it."""

    rows: list[DailyMean] = []
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames is None or "day" not in reader.fieldnames:
            raise ValidationError(f"{path} has no day column")
        for line, entry in enumerate(reader, start=2):
            try:
                mean = Decimal((entry.get("mean") or "").strip())
            except InvalidOperation as exc:
                raise ValidationError(f"line {line}: {entry.get('mean')!r} is not a flow") from exc
            rows.append(
                DailyMean(
                    day=parse_day(entry["day"]),
                    mean_cfs=mean,
                    grade=_grade((entry.get("grade") or "measured").strip()),
                )
            )
    if not rows:
        raise PolicyError(f"{path} has a header and no days")
    with context.open_current() as connection:
        load_gage(connection, code.upper())
        for reading in rows:
            record_day(connection, code.upper(), reading)
        click.echo(f"{len(rows)} days loaded onto {code.upper()}")


@gage.command("show")
@click.option("--code", required=True, help="Which gage.")
@click.option("--from", "first", required=True, help="First day to report.")
@click.option("--to", "last", required=True, help="Day after the last one.")
@click.option(
    "--floor",
    default="0.9",
    show_default=True,
    help="How much of the span has to be there before it totals.",
)
@click.pass_obj
def show(context: Context, code: str, first: str, last: str, floor: str) -> None:
    """What the creek did over a span, and where the record has holes."""

    start = parse_day(first)
    stop = parse_day(last)
    with context.open_current() as connection:
        load_gage(connection, code.upper())
        record = load_hydrograph(connection, code.upper(), start, stop)
        held = count_days(connection, code.upper())
    missing = record.missing_days(start, stop)
    covered = record.coverage(start, stop)
    pairs = [
        ("gage", code.upper()),
        ("span", f"{start} to {stop}"),
        ("days", plural(len(record.days), "day")),
        ("coverage", f"{covered}"),
        ("proved", yes_no(record.is_proved(start, stop))),
        ("on record", plural(held, "day")),
    ]
    if not missing:
        pairs.append(("volume", f"{volume(record.volume_af(start, stop, Decimal(floor)))} af"))
        pairs.append(("mean", f"{rate(record.mean_cfs(start, stop))} cfs"))
        pairs.append(("peak", f"{rate(record.peak(start, stop).mean_cfs)} cfs"))
    click.echo(field_list(pairs))
    if missing:
        click.echo()
        click.echo(f"{plural(len(missing), 'day')} missing, first {missing[0]}")
        return
    click.echo()
    columns = [Column("day"), Column("mean", Align.RIGHT), Column("grade")]
    rows = [[item.day.isoformat(), rate(item.mean_cfs), item.grade.value] for item in record.days]
    click.echo(render_table(columns, rows))


@gage.command("list")
@click.pass_obj
def list_gages(context: Context) -> None:
    """The gages on the creek, from the top down."""

    with context.open_current() as connection:
        found = gages(connection)
        if not found:
            click.echo("no gages yet")
            return
        columns = [
            Column("code"),
            Column("name"),
            Column("mile", Align.RIGHT),
            Column("days", Align.RIGHT),
        ]
        rows = [
            [item.code, item.name, f"{item.mile}", str(count_days(connection, item.code))]
            for item in found
        ]
        click.echo(render_table(columns, rows))


def register(group: click.Group) -> None:
    """Hang the gage commands off the main group."""

    group.add_command(gage)


def days_between(first: date, last: date) -> int:
    """How many days a span covers, for anybody checking a record against it."""

    if last <= first:
        raise ValidationError("a span of gage record has to end after it starts")
    return (last - first).days


def next_day(day: date) -> date:
    return day + timedelta(days=1)
