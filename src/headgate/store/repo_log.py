"""What was run against the book.

Three people share a district book: the clerk, the commissioner and whoever is
covering in August. When a season comes out wrong the first question is what
was run and by whom, and a shell history on somebody's own machine is not an
answer anybody else can get at.

Only commands that changed something are worth logging. A report run forty
times is noise, and logging it would bury the one line that matters.
"""

from __future__ import annotations

import getpass
import sqlite3
from dataclasses import dataclass
from datetime import datetime
from enum import Enum

from ..errors import NotFoundError
from .db import one, query, scalar, transaction
from .serial import instant_text, int_value, text_instant, text_value

LOG_COLUMNS = "entry_id, ran_at, operator, command, arguments, outcome"


class Outcome(Enum):
    """How the command ended."""

    DONE = "done"
    REFUSED = "refused"

    @property
    def changed_the_book(self) -> bool:
        return self is Outcome.DONE


@dataclass(frozen=True, slots=True)
class LogEntry:
    """One command, as it was run."""

    entry_id: int
    ran_at: datetime
    operator: str
    command: str
    arguments: str
    outcome: Outcome

    def describe(self) -> str:
        return (
            f"{self.ran_at:%Y-%m-%d %H:%M} {self.operator} {self.command} {self.arguments}".rstrip()
        )


def current_operator() -> str:
    """Whoever is at the keyboard, as far as the machine knows."""

    try:
        return getpass.getuser()
    except Exception:  # noqa: BLE001 - a machine with no user name is still allowed to run
        return "unknown"


def _entry_from(row: sqlite3.Row) -> LogEntry:
    return LogEntry(
        entry_id=int_value(row["entry_id"], "command_log.entry_id"),
        ran_at=text_instant(row["ran_at"], "command_log.ran_at"),
        operator=text_value(row["operator"], "command_log.operator"),
        command=text_value(row["command"], "command_log.command"),
        arguments=text_value(row["arguments"], "command_log.arguments"),
        outcome=Outcome(text_value(row["outcome"], "command_log.outcome")),
    )


def record(
    connection: sqlite3.Connection,
    command: str,
    arguments: str = "",
    outcome: Outcome = Outcome.DONE,
    operator: str | None = None,
    ran_at: datetime | None = None,
) -> LogEntry:
    """Write one line of the log and hand it back."""

    with transaction(connection):
        entry_id = int(scalar(connection, "SELECT max(entry_id) FROM command_log") or 0) + 1
        entry = LogEntry(
            entry_id=entry_id,
            ran_at=ran_at if ran_at is not None else datetime.now(),
            operator=operator if operator is not None else current_operator(),
            command=command,
            arguments=arguments,
            outcome=outcome,
        )
        connection.execute(
            f"INSERT INTO command_log ({LOG_COLUMNS}) VALUES (?, ?, ?, ?, ?, ?)",
            (
                entry.entry_id,
                instant_text(entry.ran_at),
                entry.operator,
                entry.command,
                entry.arguments,
                entry.outcome.value,
            ),
        )
    return entry


def load_entry(connection: sqlite3.Connection, entry_id: int) -> LogEntry:
    row = one(connection, f"SELECT {LOG_COLUMNS} FROM command_log WHERE entry_id = ?", (entry_id,))
    if row is None:
        raise NotFoundError("log entry", str(entry_id))
    return _entry_from(row)


def recent(connection: sqlite3.Connection, limit: int = 20) -> tuple[LogEntry, ...]:
    rows = query(
        connection,
        f"SELECT {LOG_COLUMNS} FROM command_log ORDER BY entry_id DESC LIMIT ?",
        (limit,),
    )
    return tuple(_entry_from(row) for row in rows)


def for_command(connection: sqlite3.Connection, command: str) -> tuple[LogEntry, ...]:
    rows = query(
        connection,
        f"SELECT {LOG_COLUMNS} FROM command_log WHERE command = ? ORDER BY entry_id",
        (command,),
    )
    return tuple(_entry_from(row) for row in rows)


def count_entries(connection: sqlite3.Connection) -> int:
    return int(scalar(connection, "SELECT count(*) FROM command_log") or 0)
