import sqlite3
from datetime import datetime

import pytest

from headgate.errors import NotFoundError
from headgate.store.repo_log import (
    Outcome,
    count_entries,
    current_operator,
    for_command,
    load_entry,
    recent,
    record,
)

RAN = datetime(2025, 7, 4, 12, 30)


def test_a_command_is_logged_and_read_back(book: sqlite3.Connection) -> None:
    entry = record(book, "season close", "--year 2025", operator="clerk", ran_at=RAN)
    assert load_entry(book, entry.entry_id) == entry
    assert entry.outcome.changed_the_book


def test_entries_are_numbered_in_order(book: sqlite3.Connection) -> None:
    first = record(book, "season close", operator="clerk", ran_at=RAN)
    second = record(book, "order answer", operator="clerk", ran_at=RAN)
    assert second.entry_id == first.entry_id + 1
    assert count_entries(book) == 2


def test_a_refused_command_is_logged_as_refused(book: sqlite3.Connection) -> None:
    entry = record(book, "season close", outcome=Outcome.REFUSED, operator="clerk", ran_at=RAN)
    assert not entry.outcome.changed_the_book
    assert load_entry(book, entry.entry_id).outcome is Outcome.REFUSED


def test_an_entry_that_is_not_there_is_reported_missing(book: sqlite3.Connection) -> None:
    with pytest.raises(NotFoundError, match="no log entry"):
        load_entry(book, 9)


def test_the_recent_entries_come_back_newest_first(book: sqlite3.Connection) -> None:
    record(book, "season close", operator="clerk", ran_at=RAN)
    record(book, "order answer", operator="clerk", ran_at=RAN)
    found = recent(book)
    assert [item.command for item in found] == ["order answer", "season close"]


def test_the_recent_list_can_be_cut_short(book: sqlite3.Connection) -> None:
    for _ in range(5):
        record(book, "order answer", operator="clerk", ran_at=RAN)
    assert len(recent(book, limit=2)) == 2


def test_one_command_can_be_pulled_out(book: sqlite3.Connection) -> None:
    record(book, "season close", operator="clerk", ran_at=RAN)
    record(book, "order answer", operator="clerk", ran_at=RAN)
    assert len(for_command(book, "season close")) == 1
    assert for_command(book, "nothing at all") == ()


def test_an_entry_describes_itself(book: sqlite3.Connection) -> None:
    entry = record(book, "season close", "--year 2025", operator="clerk", ran_at=RAN)
    assert entry.describe() == "2025-07-04 12:30 clerk season close --year 2025"


def test_the_operator_defaults_to_whoever_is_at_the_keyboard(
    book: sqlite3.Connection,
) -> None:
    entry = record(book, "season close", ran_at=RAN)
    assert entry.operator == current_operator()
    assert entry.operator


def test_an_empty_log_reads_empty(book: sqlite3.Connection) -> None:
    assert recent(book) == ()
    assert count_entries(book) == 0
