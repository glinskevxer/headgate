import sqlite3
from datetime import datetime
from decimal import Decimal

import pytest

from headgate.audit.journal import EntryKind
from headgate.errors import ConflictError, NotFoundError, PolicyError
from headgate.money import Money
from headgate.store.repo_journal import (
    balance_for,
    entries_about,
    load_entry,
    load_journal,
    next_sequence,
    post,
    reverse_entry,
    volume_for,
)

FIRST = datetime(2025, 7, 1, 8)
LATER = datetime(2025, 7, 8, 8)


def deliveries(book: sqlite3.Connection) -> None:
    post(book, FIRST, EntryKind.DELIVERY, "L2-14", "first set", volume_af=Decimal("12.5"))
    post(book, LATER, EntryKind.DELIVERY, "L2-14", "second set", volume_af=Decimal("8.25"))
    post(
        book,
        LATER,
        EntryKind.ASSESSMENT,
        "account 00118",
        "season bill",
        amount=Money.from_dollars("190.00"),
    )


def test_the_book_hands_out_the_sequence(book: sqlite3.Connection) -> None:
    assert next_sequence(book) == 1
    deliveries(book)
    assert next_sequence(book) == 4


def test_an_entry_comes_back_the_way_it_went_in(book: sqlite3.Connection) -> None:
    deliveries(book)
    entry = load_entry(book, 1)
    assert entry.volume_af == Decimal("12.5")
    assert entry.kind is EntryKind.DELIVERY
    assert entry.note == "first set"


def test_a_money_entry_keeps_its_cents(book: sqlite3.Connection) -> None:
    deliveries(book)
    assert load_entry(book, 3).amount == Money.from_dollars("190.00")


def test_an_entry_that_is_not_there_is_reported_missing(book: sqlite3.Connection) -> None:
    with pytest.raises(NotFoundError, match="no journal entry"):
        load_entry(book, 9)


def test_the_whole_journal_comes_back_in_sequence(book: sqlite3.Connection) -> None:
    deliveries(book)
    journal = load_journal(book)
    assert [entry.sequence for entry in journal.entries] == [1, 2, 3]
    assert journal.next_sequence == 4


def test_entries_come_back_by_subject(book: sqlite3.Connection) -> None:
    deliveries(book)
    assert len(entries_about(book, "L2-14")) == 2
    assert entries_about(book, "nobody") == ()


def test_reversing_an_entry_writes_the_opposite(book: sqlite3.Connection) -> None:
    deliveries(book)
    reversal = reverse_entry(book, 1, LATER, "weir read high")
    assert reversal.volume_af == Decimal("-12.5")
    assert reversal.reverses == 1
    assert load_entry(book, 1).volume_af == Decimal("12.5")


def test_a_reversal_takes_the_volume_back_out(book: sqlite3.Connection) -> None:
    deliveries(book)
    assert volume_for(book, "L2-14") == Decimal("20.75")
    reverse_entry(book, 1, LATER, "weir read high")
    assert volume_for(book, "L2-14") == Decimal("8.25")


def test_money_nets_off_against_a_payment(book: sqlite3.Connection) -> None:
    deliveries(book)
    post(
        book,
        LATER,
        EntryKind.PAYMENT,
        "account 00118",
        "cheque",
        amount=Money.from_dollars("-90.00"),
    )
    assert balance_for(book, "account 00118") == Money.from_dollars("100.00")


def test_an_entry_cannot_be_reversed_twice(book: sqlite3.Connection) -> None:
    deliveries(book)
    reverse_entry(book, 1, LATER, "weir read high")
    with pytest.raises(ConflictError, match="already been reversed"):
        reverse_entry(book, 1, LATER, "again")


def test_a_reversal_cannot_itself_be_reversed(book: sqlite3.Connection) -> None:
    deliveries(book)
    reverse_entry(book, 1, LATER, "weir read high")
    with pytest.raises(PolicyError, match="itself a reversal"):
        reverse_entry(book, 4, LATER, "put it back")


def test_the_book_refuses_a_reversal_of_a_later_entry(book: sqlite3.Connection) -> None:
    deliveries(book)
    with pytest.raises(sqlite3.IntegrityError):
        book.execute(
            "INSERT INTO journal_entry (sequence, recorded_at, kind, subject, note, reverses)"
            " VALUES (4, '2025-07-08 08:00:00', 'delivery', 'L2-14', 'odd', 9)"
        )


def test_an_empty_journal_reads_as_empty(book: sqlite3.Connection) -> None:
    assert load_journal(book).entries == ()
    assert volume_for(book, "L2-14") == Decimal("0")
    assert balance_for(book, "account 00118") == Money.zero()
