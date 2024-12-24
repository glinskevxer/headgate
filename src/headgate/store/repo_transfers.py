"""Reading and writing transfer applications.

An application is written once and then moved along its course, so the row is
updated in place for the status and the terms and nothing else. What was asked
for, when it was filed and what the study proved are written at filing and are
never touched again, because those are the facts a protest is argued against.

The study itself is not stored. It is rebuilt from the delivery record when
anybody wants to see it, and storing a summary of it would let the two drift
apart, which is the one thing a transfer file cannot survive.
"""

from __future__ import annotations

import sqlite3
from decimal import Decimal

from ..duty.hcu import HistoricalUse, YearFinding
from ..errors import ConflictError, NotFoundError
from ..ids import DecreeNumber, TurnoutCode
from ..transfer.application import (
    TransferApplication,
    TransferKind,
    TransferStatus,
    TransferTerms,
)
from .db import one, query, transaction
from .serial import (
    code_text,
    date_text,
    decimal_text,
    enum_text,
    int_flag,
    optional_decimal,
    optional_decimal_text,
    text_date,
    text_decimal,
    text_enum,
    text_value,
)

APPLICATION_COLUMNS = (
    "number, decree, kind, filed_on, requested_af, proved_af, from_turnout, to_turnout,"
    " status, note, approved_af, return_flow_af"
)


def _study(proved_af: Decimal) -> HistoricalUse:
    """A study stub carrying the number the application was filed against."""

    return HistoricalUse(
        findings=(YearFinding(0, proved_af, True, "as filed"),), average_af=proved_af
    )


def _dry_up_for(connection: sqlite3.Connection, number: str) -> tuple[str, ...]:
    rows = query(
        connection,
        "SELECT parcel_id, offered FROM transfer_dry_up WHERE number = ? ORDER BY parcel_id",
        (number,),
    )
    return tuple(
        text_value(row["parcel_id"], "transfer_dry_up.parcel_id")
        for row in rows
        if int_flag(row["offered"], "transfer_dry_up.offered")
    )


def _conditions_for(connection: sqlite3.Connection, number: str) -> tuple[str, ...]:
    rows = query(
        connection,
        "SELECT condition FROM transfer_condition WHERE number = ? ORDER BY ordinal",
        (number,),
    )
    return tuple(text_value(row["condition"], "transfer_condition.condition") for row in rows)


def _application_from(connection: sqlite3.Connection, row: sqlite3.Row) -> TransferApplication:
    number = text_value(row["number"], "transfer_application.number")
    approved = optional_decimal(row["approved_af"], "transfer_application.approved_af")
    dry_up = _dry_up_for(connection, number)
    terms = None
    if approved is not None:
        terms = TransferTerms(
            approved_af=approved,
            dry_up_parcels=dry_up,
            return_flow_af=optional_decimal(
                row["return_flow_af"], "transfer_application.return_flow_af"
            )
            or Decimal("0"),
            conditions=_conditions_for(connection, number),
        )
    from_turnout = row["from_turnout"]
    to_turnout = row["to_turnout"]
    return TransferApplication(
        number=number,
        decree=DecreeNumber(text_value(row["decree"], "transfer_application.decree")),
        kind=text_enum(TransferKind, row["kind"], "transfer_application.kind"),
        filed_on=text_date(row["filed_on"], "transfer_application.filed_on"),
        requested_af=text_decimal(row["requested_af"], "transfer_application.requested_af"),
        study=_study(text_decimal(row["proved_af"], "transfer_application.proved_af")),
        from_turnout=TurnoutCode(text_value(from_turnout, "transfer_application.from_turnout"))
        if from_turnout is not None
        else None,
        to_turnout=TurnoutCode(text_value(to_turnout, "transfer_application.to_turnout"))
        if to_turnout is not None
        else None,
        dry_up_parcels=dry_up,
        status=text_enum(TransferStatus, row["status"], "transfer_application.status"),
        terms=terms,
        note=text_value(row["note"], "transfer_application.note"),
    )


def file_application(connection: sqlite3.Connection, application: TransferApplication) -> None:
    """Write a new application. Filing the same number twice is a conflict."""

    existing = one(
        connection,
        "SELECT number FROM transfer_application WHERE number = ?",
        (application.number,),
    )
    if existing is not None:
        raise ConflictError(f"application {application.number} has already been filed")
    with transaction(connection):
        connection.execute(
            f"INSERT INTO transfer_application ({APPLICATION_COLUMNS})"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                application.number,
                str(application.decree),
                enum_text(application.kind),
                date_text(application.filed_on),
                decimal_text(application.requested_af),
                decimal_text(application.study.average_af),
                code_text(application.from_turnout),
                code_text(application.to_turnout),
                enum_text(application.status),
                application.note,
                optional_decimal_text(
                    application.terms.approved_af if application.terms is not None else None
                ),
                optional_decimal_text(
                    application.terms.return_flow_af if application.terms is not None else None
                ),
            ),
        )
        for parcel in application.dry_up_parcels:
            connection.execute(
                "INSERT INTO transfer_dry_up (number, parcel_id, offered) VALUES (?, ?, 1)",
                (application.number, parcel),
            )


def save_application(connection: sqlite3.Connection, application: TransferApplication) -> None:
    """Write where an application has got to, and its terms if it has any."""

    load_application(connection, application.number)
    with transaction(connection):
        connection.execute(
            "UPDATE transfer_application SET status = ?, note = ?, approved_af = ?,"
            " return_flow_af = ? WHERE number = ?",
            (
                enum_text(application.status),
                application.note,
                optional_decimal_text(
                    application.terms.approved_af if application.terms is not None else None
                ),
                optional_decimal_text(
                    application.terms.return_flow_af if application.terms is not None else None
                ),
                application.number,
            ),
        )
        connection.execute("DELETE FROM transfer_condition WHERE number = ?", (application.number,))
        if application.terms is not None:
            for ordinal, condition in enumerate(application.terms.conditions, start=1):
                connection.execute(
                    "INSERT INTO transfer_condition (number, ordinal, condition) VALUES (?, ?, ?)",
                    (application.number, ordinal, condition),
                )


def load_application(connection: sqlite3.Connection, number: str) -> TransferApplication:
    row = one(
        connection,
        f"SELECT {APPLICATION_COLUMNS} FROM transfer_application WHERE number = ?",
        (number,),
    )
    if row is None:
        raise NotFoundError("transfer application", number)
    return _application_from(connection, row)


def applications_on(
    connection: sqlite3.Connection, decree: DecreeNumber
) -> tuple[TransferApplication, ...]:
    rows = query(
        connection,
        f"SELECT {APPLICATION_COLUMNS} FROM transfer_application WHERE decree = ?"
        " ORDER BY filed_on, number",
        (str(decree),),
    )
    return tuple(_application_from(connection, row) for row in rows)


def open_applications(connection: sqlite3.Connection) -> tuple[TransferApplication, ...]:
    """Everything still moving, which is what the office chases."""

    rows = query(
        connection,
        f"SELECT {APPLICATION_COLUMNS} FROM transfer_application"
        " WHERE status IN ('filed', 'published', 'protested') ORDER BY filed_on, number",
    )
    return tuple(_application_from(connection, row) for row in rows)


def approved_volume_on(connection: sqlite3.Connection, decree: DecreeNumber) -> Decimal:
    """How much of a right has already been moved off it."""

    total = Decimal("0")
    for application in applications_on(connection, decree):
        if application.status is TransferStatus.APPROVED and application.terms is not None:
            total += application.terms.approved_af
    return total
