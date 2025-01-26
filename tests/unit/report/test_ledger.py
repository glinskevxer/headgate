from datetime import datetime
from decimal import Decimal

import pytest

from headgate.audit.journal import EntryKind, Journal
from headgate.errors import PolicyError
from headgate.money import Money
from headgate.report.ledger import build

FIRST = datetime(2025, 7, 1, 8)
LATER = datetime(2025, 8, 8, 8)


def journal() -> Journal:
    return (
        Journal()
        .append(FIRST, EntryKind.DELIVERY, "L2-14", "first set", volume_af=Decimal("12.5"))
        .append(LATER, EntryKind.DELIVERY, "L2-20", "second set", volume_af=Decimal("8.25"))
        .append(
            LATER,
            EntryKind.ASSESSMENT,
            "account 00118",
            "season bill",
            amount=Money.from_dollars("190.00"),
        )
        .reverse(1, LATER, "weir read high")
    )


def test_the_whole_journal_reports_as_it_stands() -> None:
    built = build(journal().entries)
    assert len(built.entries) == 4
    assert built.volume_af == Decimal("8.2500")
    assert built.amount == Money.from_dollars("190.00")


def test_a_reversal_is_kept_rather_than_netted_out() -> None:
    built = build(journal().entries)
    assert len(built.reversals) == 1
    assert any("reverses 00001" in row[-1] for row in built.rows())


def test_one_subject_can_be_pulled_out() -> None:
    built = build(journal().entries, subject="L2-14")
    assert built.subjects == ("L2-14",)
    assert built.volume_af == Decimal("0")


def test_one_kind_can_be_pulled_out() -> None:
    built = build(journal().entries, kind=EntryKind.ASSESSMENT)
    assert len(built.entries) == 1
    assert built.amount == Money.from_dollars("190.00")


def test_a_span_cuts_the_journal_down() -> None:
    built = build(journal().entries, first=datetime(2025, 8, 1), last=datetime(2025, 9, 1))
    assert all(item.recorded_at >= datetime(2025, 8, 1) for item in built.entries)
    assert len(built.entries) == 3


def test_a_span_that_ends_before_it_starts_is_refused() -> None:
    with pytest.raises(PolicyError, match="ends after it starts"):
        build(journal().entries, first=datetime(2025, 9, 1), last=datetime(2025, 8, 1))


def test_a_filter_that_matches_nothing_reports_empty() -> None:
    built = build(journal().entries, subject="nobody")
    assert built.is_empty
    assert built.rows() == []


def test_the_entries_come_back_in_sequence() -> None:
    built = build(tuple(reversed(journal().entries)))
    assert [item.sequence for item in built.entries] == [1, 2, 3, 4]


def test_the_summary_says_what_was_asked_for() -> None:
    summary = dict(build(journal().entries, subject="L2-14").summary())
    assert summary["subject"] == "L2-14"
    assert summary["kind"] == "everything"
    assert summary["reversals"] == "1"


def test_the_rows_print_a_dash_where_there_is_no_number() -> None:
    rows = build(journal().entries, kind=EntryKind.ASSESSMENT).rows()
    assert rows[0][4] == "-"
    assert rows[0][5] == "$190.00"
