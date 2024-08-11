"""Reading and writing the journal.

The sequence comes out of the book rather than out of the caller, so two
sessions writing at once cannot both think they are entry 412. Everything goes
in inside one transaction that reads the highest sequence and inserts the next
one, which SQLite serialises for us as long as the write begins immediately.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime
from decimal import Decimal

from ..audit.journal import Entry, EntryKind, Journal
from ..errors import ConflictError, NotFoundError, PolicyError
from ..money import Money
from .db import one, query, scalar, transaction
from .serial import (
    enum_text,
    instant_text,
    int_value,
    optional_decimal,
    optional_decimal_text,
    text_enum,
    text_instant,
    text_value,
)

ENTRY_COLUMNS = "sequence, recorded_at, kind, subject, note, volume_af, amount_cents, reverses"


def _entry_from(row: sqlite3.Row) -> Entry:
    amount = row["amount_cents"]
    reverses = row["reverses"]
    return Entry(
        sequence=int_value(row["sequence"], "journal_entry.sequence"),
        recorded_at=text_instant(row["recorded_at"], "journal_entry.recorded_at"),
        kind=text_enum(EntryKind, row["kind"], "journal_entry.kind"),
        subject=text_value(row["subject"], "journal_entry.subject"),
        note=text_value(row["note"], "journal_entry.note"),
        volume_af=optional_decimal(row["volume_af"], "journal_entry.volume_af"),
        amount=Money(int_value(amount, "journal_entry.amount_cents"))
        if amount is not None
        else None,
        reverses=int_value(reverses, "journal_entry.reverses") if reverses is not None else None,
    )


def next_sequence(connection: sqlite3.Connection) -> int:
    highest = scalar(connection, "SELECT max(sequence) FROM journal_entry")
    return 1 if highest is None else int(highest) + 1


def post(
    connection: sqlite3.Connection,
    recorded_at: datetime,
    kind: EntryKind,
    subject: str,
    note: str = "",
    volume_af: Decimal | None = None,
    amount: Money | None = None,
    reverses: int | None = None,
) -> Entry:
    """Write one entry and hand back what was written."""

    with transaction(connection):
        sequence = next_sequence(connection)
        entry = Entry(
            sequence=sequence,
            recorded_at=recorded_at,
            kind=kind,
            subject=subject,
            note=note,
            volume_af=volume_af,
            amount=amount,
            reverses=reverses,
        )
        connection.execute(
            f"INSERT INTO journal_entry ({ENTRY_COLUMNS}) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                entry.sequence,
                instant_text(entry.recorded_at),
                enum_text(entry.kind),
                entry.subject,
                entry.note,
                optional_decimal_text(entry.volume_af),
                entry.amount.cents if entry.amount is not None else None,
                entry.reverses,
            ),
        )
    return entry


def load_entry(connection: sqlite3.Connection, sequence: int) -> Entry:
    row = one(
        connection, f"SELECT {ENTRY_COLUMNS} FROM journal_entry WHERE sequence = ?", (sequence,)
    )
    if row is None:
        raise NotFoundError("journal entry", str(sequence))
    return _entry_from(row)


def load_journal(connection: sqlite3.Connection) -> Journal:
    rows = query(connection, f"SELECT {ENTRY_COLUMNS} FROM journal_entry ORDER BY sequence")
    return Journal(entries=tuple(_entry_from(row) for row in rows))


def entries_about(connection: sqlite3.Connection, subject: str) -> tuple[Entry, ...]:
    rows = query(
        connection,
        f"SELECT {ENTRY_COLUMNS} FROM journal_entry WHERE subject = ? ORDER BY sequence",
        (subject,),
    )
    return tuple(_entry_from(row) for row in rows)


def reverse_entry(
    connection: sqlite3.Connection, sequence: int, recorded_at: datetime, note: str
) -> Entry:
    """Answer an entry with its opposite, refusing to do it twice."""

    original = load_entry(connection, sequence)
    if original.is_a_reversal:
        raise PolicyError(f"entry {sequence} is itself a reversal")
    existing = one(connection, "SELECT sequence FROM journal_entry WHERE reverses = ?", (sequence,))
    if existing is not None:
        raise ConflictError(f"entry {sequence} has already been reversed")
    return post(
        connection,
        recorded_at=recorded_at,
        kind=original.kind,
        subject=original.subject,
        note=note,
        volume_af=-original.volume_af if original.volume_af is not None else None,
        amount=-original.amount if original.amount is not None else None,
        reverses=sequence,
    )


def volume_for(connection: sqlite3.Connection, subject: str) -> Decimal:
    return sum(
        (
            entry.volume_af
            for entry in entries_about(connection, subject)
            if entry.volume_af is not None
        ),
        Decimal("0"),
    )


def balance_for(connection: sqlite3.Connection, subject: str) -> Money:
    total = Money.zero()
    for entry in entries_about(connection, subject):
        if entry.amount is not None:
            total = total + entry.amount
    return total
