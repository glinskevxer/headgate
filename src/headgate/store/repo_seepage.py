"""Reading and writing the seepage runs.

A run is a measurement made on a day and it is never edited. Running the same
reach again on another day is another row, which is the whole point: the file
shows a ditch getting worse over five years rather than one number that
somebody changed twice.
"""

from __future__ import annotations

import sqlite3
from decimal import Decimal

from ..errors import ConflictError, PolicyError
from ..ids import DitchCode
from ..model.ditch import Ditch, DitchSystem
from ..model.seepage import SeepageHistory, SeepageRun
from .db import one, query, transaction
from .repo_ditch import load_system, save_system
from .serial import date_text, decimal_text, text_date, text_decimal, text_value

RUN_COLUMNS = (
    "ditch_code, run_on, from_station_feet, to_station_feet, inflow_cfs, outflow_cfs,"
    " turnouts_cfs, flume_error_cfs, note"
)


def _run_from(row: sqlite3.Row) -> SeepageRun:
    return SeepageRun(
        ditch=DitchCode(text_value(row["ditch_code"], "seepage_run.ditch_code")),
        run_on=text_date(row["run_on"], "seepage_run.run_on"),
        from_station_feet=text_decimal(row["from_station_feet"], "seepage_run.from_station_feet"),
        to_station_feet=text_decimal(row["to_station_feet"], "seepage_run.to_station_feet"),
        inflow_cfs=text_decimal(row["inflow_cfs"], "seepage_run.inflow_cfs"),
        outflow_cfs=text_decimal(row["outflow_cfs"], "seepage_run.outflow_cfs"),
        turnouts_running_cfs=text_decimal(row["turnouts_cfs"], "seepage_run.turnouts_cfs"),
        flume_error_cfs=text_decimal(row["flume_error_cfs"], "seepage_run.flume_error_cfs"),
        note=text_value(row["note"], "seepage_run.note"),
    )


def record_run(connection: sqlite3.Connection, run: SeepageRun) -> None:
    """Write a run. The same reach on the same day twice is a conflict."""

    existing = one(
        connection,
        "SELECT run_on FROM seepage_run WHERE ditch_code = ? AND run_on = ?"
        " AND from_station_feet = ?",
        (str(run.ditch), date_text(run.run_on), decimal_text(run.from_station_feet)),
    )
    if existing is not None:
        raise ConflictError(
            f"{run.ditch} was already run from station {run.from_station_feet} on {run.run_on}"
        )
    with transaction(connection):
        connection.execute(
            f"INSERT INTO seepage_run ({RUN_COLUMNS}) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                str(run.ditch),
                date_text(run.run_on),
                decimal_text(run.from_station_feet),
                decimal_text(run.to_station_feet),
                decimal_text(run.inflow_cfs),
                decimal_text(run.outflow_cfs),
                decimal_text(run.turnouts_running_cfs),
                decimal_text(run.flume_error_cfs),
                run.note,
            ),
        )


def load_history(connection: sqlite3.Connection, ditch: DitchCode) -> SeepageHistory:
    rows = query(
        connection,
        f"SELECT {RUN_COLUMNS} FROM seepage_run WHERE ditch_code = ?"
        " ORDER BY run_on, from_station_feet",
        (str(ditch),),
    )
    return SeepageHistory(ditch=ditch, runs=tuple(_run_from(row) for row in rows))


def adopt_measured_rate(connection: sqlite3.Connection, ditch: DitchCode) -> Decimal:
    """Put the measured loss rate on the ditch, where the carriage reads it.

    This is the point of running a seepage test. Until the rate is adopted the
    runs are a file note; afterwards every carriage calculation, every loss
    charged out and every bill built off one uses the measured number.
    """

    history = load_history(connection, ditch)
    measured = history.measured_loss_per_mile()
    if measured <= 0:
        raise PolicyError(
            f"{ditch} measured a gain of {abs(measured)} a mile, which is not a loss rate"
        )
    system = load_system(connection)
    target = system.ditch(ditch)
    rebuilt = tuple(
        Ditch(
            code=item.code,
            name=item.name,
            capacity_cfs=item.capacity_cfs,
            length_feet=item.length_feet,
            loss_fraction_per_mile=measured
            if item.code == target.code
            else item.loss_fraction_per_mile,
            turnouts=item.turnouts,
            parent=item.parent,
            offtake_station_feet=item.offtake_station_feet,
            diversion_mile=item.diversion_mile,
        )
        for item in system.ditches
    )
    save_system(connection, DitchSystem(ditches=rebuilt))
    return measured


def ditches_run(connection: sqlite3.Connection) -> tuple[DitchCode, ...]:
    rows = query(connection, "SELECT DISTINCT ditch_code FROM seepage_run ORDER BY ditch_code")
    return tuple(DitchCode(text_value(row["ditch_code"], "seepage_run.ditch_code")) for row in rows)
