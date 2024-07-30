from datetime import datetime
from decimal import Decimal

import pytest

from headgate.audit.journal import Entry, EntryKind, Journal
from headgate.errors import ConflictError, NotFoundError, PolicyError, ValidationError
from headgate.money import Money

FIRST = datetime(2025, 7, 1, 8)
LATER = datetime(2025, 7, 8, 8)


def journal() -> Journal:
    return (
        Journal()
        .append(FIRST, EntryKind.DELIVERY, "L2-14", "first set", volume_af=Decimal("12.5"))
        .append(LATER, EntryKind.DELIVERY, "L2-14", "second set", volume_af=Decimal("8.25"))
        .append(
            LATER,
            EntryKind.ASSESSMENT,
            "account 00118",
            "season bill",
            amount=Money.from_dollars("190.00"),
        )
    )


def test_entries_are_numbered_from_one() -> None:
    assert [item.sequence for item in journal().entries] == [1, 2, 3]
    assert journal().next_sequence == 4


def test_a_delivery_entry_needs_a_volume() -> None:
    with pytest.raises(ValidationError, match="no volume"):
        Journal().append(FIRST, EntryKind.DELIVERY, "L2-14", "no water on it")


def test_an_assessment_entry_needs_an_amount() -> None:
    with pytest.raises(ValidationError, match="no amount"):
        Journal().append(FIRST, EntryKind.ASSESSMENT, "account 00118", "no money on it")


def test_an_entry_is_about_something() -> None:
    with pytest.raises(ValidationError, match="nothing in particular"):
        Journal().append(FIRST, EntryKind.CURTAILMENT, "   ", "nobody")


def test_a_sequence_starts_at_one() -> None:
    with pytest.raises(ValidationError, match="not a journal sequence"):
        Entry(0, FIRST, EntryKind.CURTAILMENT, "CDA-1920-5", "shut")


def test_a_journal_with_a_gap_is_refused() -> None:
    entries = journal().entries
    with pytest.raises(ValidationError, match="jumps from"):
        Journal(entries=(entries[0], entries[2]))


def test_an_entry_can_be_looked_up_by_sequence() -> None:
    assert journal().entry(2).note == "second set"
    with pytest.raises(NotFoundError, match="no journal entry"):
        journal().entry(9)


def test_reversing_an_entry_leaves_the_original_alone() -> None:
    reversed_journal = journal().reverse(1, LATER, "weir read high")
    assert reversed_journal.entry(1).volume_af == Decimal("12.5")
    assert reversed_journal.entry(4).volume_af == Decimal("-12.5")
    assert reversed_journal.is_reversed(1)


def test_a_reversal_carries_the_kind_and_the_subject() -> None:
    reversed_journal = journal().reverse(3, LATER, "billed off the wrong reading")
    reversal = reversed_journal.entry(4)
    assert reversal.kind is EntryKind.ASSESSMENT
    assert reversal.subject == "account 00118"
    assert reversal.amount == Money.from_dollars("-190.00")


def test_an_entry_cannot_be_reversed_twice() -> None:
    once = journal().reverse(1, LATER, "weir read high")
    with pytest.raises(ConflictError, match="already been reversed"):
        once.reverse(1, LATER, "again")


def test_a_reversal_cannot_itself_be_reversed() -> None:
    once = journal().reverse(1, LATER, "weir read high")
    with pytest.raises(PolicyError, match="itself a reversal"):
        once.reverse(4, LATER, "put it back")


def test_a_reversal_has_to_point_backwards() -> None:
    with pytest.raises(ValidationError, match="not behind it"):
        Entry(2, FIRST, EntryKind.DELIVERY, "L2-14", "odd", volume_af=Decimal("1"), reverses=5)


def test_a_reversal_of_an_entry_that_is_not_there_is_refused() -> None:
    entry = Entry(1, FIRST, EntryKind.DELIVERY, "L2-14", "odd", volume_af=Decimal("1"))
    reversal = Entry(
        2, LATER, EntryKind.DELIVERY, "L2-14", "odd", volume_af=Decimal("-1"), reverses=1
    )
    Journal(entries=(entry, reversal))


def test_volumes_add_up_by_subject() -> None:
    assert journal().volume_for("L2-14") == Decimal("20.7500")


def test_a_reversal_takes_the_volume_back_out() -> None:
    reversed_journal = journal().reverse(1, LATER, "weir read high")
    assert reversed_journal.volume_for("L2-14") == Decimal("8.2500")


def test_money_adds_up_by_subject() -> None:
    paid = journal().append(
        LATER, EntryKind.PAYMENT, "account 00118", "cheque", amount=Money.from_dollars("-90.00")
    )
    assert paid.balance_for("account 00118") == Money.from_dollars("100.00")


def test_entries_are_listed_by_subject_and_by_kind() -> None:
    assert len(journal().about("L2-14")) == 2
    assert len(journal().of_kind(EntryKind.ASSESSMENT)) == 1


def test_entries_can_be_pulled_out_by_date() -> None:
    found = journal().between(datetime(2025, 7, 5), datetime(2025, 7, 10))
    assert [item.sequence for item in found] == [2, 3]


def test_an_entry_describes_itself_for_the_printed_journal() -> None:
    text = journal().entry(1).describe()
    assert "00001" in text
    assert "delivery" in text
    assert "12.5000 af" in text


def test_a_money_entry_describes_its_amount() -> None:
    assert "$190.00" in journal().entry(3).describe()
