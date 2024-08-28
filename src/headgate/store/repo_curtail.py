"""Reading and writing the curtailment notices.

A notice is written once and the only column that ever changes on it is the
lift date. The key is the right, the call it was served for, and the moment it
was issued, which is exactly the combination that cannot happen twice.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime

from ..errors import ConflictError
from ..ids import DecreeNumber
from ..priority.curtail import CurtailmentNotice, CurtailmentRegister
from .db import query, transaction
from .serial import (
    decimal_text,
    instant_text,
    text_decimal,
    text_instant,
    text_value,
)

NOTICE_COLUMNS = (
    "decree, called_by, issued_at, effective_at, curtailed_cfs, allowed_cfs, reason, lifted_at"
)


def _notice_from(row: sqlite3.Row) -> CurtailmentNotice:
    lifted = row["lifted_at"]
    return CurtailmentNotice(
        decree=DecreeNumber(text_value(row["decree"], "curtailment_notice.decree")),
        called_by=DecreeNumber(text_value(row["called_by"], "curtailment_notice.called_by")),
        issued_at=text_instant(row["issued_at"], "curtailment_notice.issued_at"),
        effective_at=text_instant(row["effective_at"], "curtailment_notice.effective_at"),
        curtailed_cfs=text_decimal(row["curtailed_cfs"], "curtailment_notice.curtailed_cfs"),
        allowed_cfs=text_decimal(row["allowed_cfs"], "curtailment_notice.allowed_cfs"),
        reason=text_value(row["reason"], "curtailment_notice.reason"),
        lifted_at=text_instant(lifted, "curtailment_notice.lifted_at")
        if lifted is not None
        else None,
    )


def serve_notice(connection: sqlite3.Connection, notice: CurtailmentNotice) -> None:
    """Write a notice. The same notice twice is a conflict, not an update."""

    try:
        with transaction(connection):
            connection.execute(
                f"INSERT INTO curtailment_notice ({NOTICE_COLUMNS})"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    str(notice.decree),
                    str(notice.called_by),
                    instant_text(notice.issued_at),
                    instant_text(notice.effective_at),
                    decimal_text(notice.curtailed_cfs),
                    decimal_text(notice.allowed_cfs),
                    notice.reason,
                    instant_text(notice.lifted_at) if notice.lifted_at is not None else None,
                ),
            )
    except sqlite3.IntegrityError as exc:
        if "UNIQUE" in str(exc).upper() or "PRIMARY KEY" in str(exc).upper():
            raise ConflictError(
                f"a notice on {notice.decree} for the call by {notice.called_by} was already "
                f"served at {notice.issued_at}"
            ) from exc
        raise


def load_register(connection: sqlite3.Connection) -> CurtailmentRegister:
    rows = query(
        connection,
        f"SELECT {NOTICE_COLUMNS} FROM curtailment_notice ORDER BY issued_at, decree",
    )
    return CurtailmentRegister(notices=tuple(_notice_from(row) for row in rows))


def standing_at(connection: sqlite3.Connection, moment: datetime) -> tuple[CurtailmentNotice, ...]:
    """The notices in force at a moment, straight out of the book."""

    rows = query(
        connection,
        f"SELECT {NOTICE_COLUMNS} FROM curtailment_notice WHERE effective_at <= ?"
        " AND (lifted_at IS NULL OR lifted_at > ?) ORDER BY decree",
        (instant_text(moment), instant_text(moment)),
    )
    return tuple(_notice_from(row) for row in rows)


def lift_notice(
    connection: sqlite3.Connection,
    decree: DecreeNumber,
    called_by: DecreeNumber,
    issued_at: datetime,
    lifted_at: datetime,
) -> bool:
    """Write the lift date on one notice."""

    with transaction(connection):
        cursor = connection.execute(
            "UPDATE curtailment_notice SET lifted_at = ?"
            " WHERE decree = ? AND called_by = ? AND issued_at = ? AND lifted_at IS NULL",
            (instant_text(lifted_at), str(decree), str(called_by), instant_text(issued_at)),
        )
        changed = cursor.rowcount
        cursor.close()
    return changed > 0


def lift_call(connection: sqlite3.Connection, called_by: DecreeNumber, lifted_at: datetime) -> int:
    """Lift every notice served for one call, which is how a call ends."""

    with transaction(connection):
        cursor = connection.execute(
            "UPDATE curtailment_notice SET lifted_at = ? WHERE called_by = ? AND lifted_at IS NULL",
            (instant_text(lifted_at), str(called_by)),
        )
        changed = cursor.rowcount
        cursor.close()
    return changed
