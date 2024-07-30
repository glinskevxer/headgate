"""An append only journal of everything the district did.

Deliveries, curtailments, bills, payments and restatements all land here in one
sequence. Nothing is ever changed and nothing is ever removed. An entry that
was wrong is answered by a reversing entry that points at it, which is how the
books stay tied to what was actually done rather than to what somebody wishes
had been done.

The sequence is dense and it is checked. A gap in the numbers means an entry
went missing, and finding that out at the end of a season is much too late.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime
from decimal import Decimal
from enum import Enum

from ..errors import ConflictError, NotFoundError, PolicyError, ValidationError
from ..money import Money
from ..units import round_volume


class EntryKind(Enum):
    """What sort of thing happened."""

    DELIVERY = "delivery"
    CURTAILMENT = "curtailment"
    CALIBRATION = "calibration"
    ASSESSMENT = "assessment"
    PAYMENT = "payment"
    TRANSFER = "transfer"
    RESTATEMENT = "restatement"

    @property
    def carries_water(self) -> bool:
        return self in {EntryKind.DELIVERY, EntryKind.TRANSFER}

    @property
    def carries_money(self) -> bool:
        return self in {EntryKind.ASSESSMENT, EntryKind.PAYMENT, EntryKind.RESTATEMENT}


@dataclass(frozen=True, slots=True)
class Entry:
    """One line of the journal."""

    sequence: int
    recorded_at: datetime
    kind: EntryKind
    subject: str
    note: str
    volume_af: Decimal | None = None
    amount: Money | None = None
    reverses: int | None = None

    def __post_init__(self) -> None:
        if self.sequence < 1:
            raise ValidationError(f"{self.sequence} is not a journal sequence")
        if not self.subject.strip():
            raise ValidationError(f"entry {self.sequence} is about nothing in particular")
        if self.kind.carries_water and self.volume_af is None:
            raise ValidationError(f"entry {self.sequence} is a {self.kind.value} with no volume")
        if self.kind.carries_money and self.amount is None:
            raise ValidationError(f"entry {self.sequence} is a {self.kind.value} with no amount")
        if self.reverses is not None and self.reverses >= self.sequence:
            raise ValidationError(
                f"entry {self.sequence} claims to reverse {self.reverses}, which is not behind it"
            )

    @property
    def is_a_reversal(self) -> bool:
        return self.reverses is not None

    def describe(self) -> str:
        pieces = [
            f"{self.sequence:05d}",
            self.recorded_at.strftime("%Y-%m-%d"),
            self.kind.value,
            self.subject,
        ]
        if self.volume_af is not None:
            pieces.append(f"{round_volume(self.volume_af)} af")
        if self.amount is not None:
            pieces.append(str(self.amount))
        pieces.append(self.note)
        return "  ".join(piece for piece in pieces if piece)


@dataclass(frozen=True, slots=True)
class Journal:
    """Every entry, in sequence."""

    entries: tuple[Entry, ...] = ()

    def __post_init__(self) -> None:
        for expected, entry in enumerate(self.entries, start=1):
            if entry.sequence != expected:
                raise ValidationError(f"the journal jumps from {expected - 1} to {entry.sequence}")
        for entry in self.entries:
            if entry.reverses is not None and entry.reverses > len(self.entries):
                raise ValidationError(
                    f"entry {entry.sequence} reverses {entry.reverses}, which is not in the journal"
                )

    @property
    def next_sequence(self) -> int:
        return len(self.entries) + 1

    def entry(self, sequence: int) -> Entry:
        for item in self.entries:
            if item.sequence == sequence:
                return item
        raise NotFoundError("journal entry", str(sequence))

    def append(
        self,
        recorded_at: datetime,
        kind: EntryKind,
        subject: str,
        note: str = "",
        volume_af: Decimal | None = None,
        amount: Money | None = None,
    ) -> Journal:
        entry = Entry(
            sequence=self.next_sequence,
            recorded_at=recorded_at,
            kind=kind,
            subject=subject,
            note=note,
            volume_af=volume_af,
            amount=amount,
        )
        return replace(self, entries=(*self.entries, entry))

    def reverse(self, sequence: int, recorded_at: datetime, note: str) -> Journal:
        """Answer an entry with its opposite, leaving the original alone."""

        original = self.entry(sequence)
        if original.is_a_reversal:
            raise PolicyError(f"entry {sequence} is itself a reversal")
        if self.reversal_of(sequence) is not None:
            raise ConflictError(f"entry {sequence} has already been reversed")
        entry = Entry(
            sequence=self.next_sequence,
            recorded_at=recorded_at,
            kind=original.kind,
            subject=original.subject,
            note=note,
            volume_af=-original.volume_af if original.volume_af is not None else None,
            amount=-original.amount if original.amount is not None else None,
            reverses=sequence,
        )
        return replace(self, entries=(*self.entries, entry))

    def reversal_of(self, sequence: int) -> Entry | None:
        for item in self.entries:
            if item.reverses == sequence:
                return item
        return None

    def is_reversed(self, sequence: int) -> bool:
        return self.reversal_of(sequence) is not None

    def about(self, subject: str) -> tuple[Entry, ...]:
        return tuple(item for item in self.entries if item.subject == subject)

    def of_kind(self, kind: EntryKind) -> tuple[Entry, ...]:
        return tuple(item for item in self.entries if item.kind is kind)

    def volume_for(self, subject: str) -> Decimal:
        return round_volume(
            sum(
                (item.volume_af for item in self.about(subject) if item.volume_af is not None),
                Decimal("0"),
            )
        )

    def balance_for(self, subject: str) -> Money:
        total = Money.zero()
        for item in self.about(subject):
            if item.amount is not None:
                total = total + item.amount
        return total

    def between(self, first: datetime, last: datetime) -> tuple[Entry, ...]:
        return tuple(item for item in self.entries if first <= item.recorded_at < last)
