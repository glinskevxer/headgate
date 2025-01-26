"""The journal, printed.

Everything the district did, in sequence, filtered down to the part somebody
asked about. The report keeps the reversals in rather than netting them out,
because an entry that was made and then answered is a different story from an
entry that was never made, and the whole reason for an append only journal is
to be able to tell the two apart.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from ..audit.journal import Entry, EntryKind
from ..errors import PolicyError
from ..money import Money
from ..units import round_volume


@dataclass(frozen=True, slots=True)
class LedgerReport:
    """A slice of the journal, with what it adds up to."""

    entries: tuple[Entry, ...]
    subject: str | None = None
    kind: EntryKind | None = None

    @property
    def volume_af(self) -> Decimal:
        return round_volume(
            sum(
                (item.volume_af for item in self.entries if item.volume_af is not None),
                Decimal("0"),
            )
        )

    @property
    def amount(self) -> Money:
        total = Money.zero()
        for item in self.entries:
            if item.amount is not None:
                total = total + item.amount
        return total

    @property
    def reversals(self) -> tuple[Entry, ...]:
        return tuple(item for item in self.entries if item.is_a_reversal)

    @property
    def subjects(self) -> tuple[str, ...]:
        return tuple(sorted({item.subject for item in self.entries}))

    @property
    def is_empty(self) -> bool:
        return not self.entries

    def rows(self) -> list[list[str]]:
        return [
            [
                f"{item.sequence:05d}",
                f"{item.recorded_at:%Y-%m-%d}",
                item.kind.value,
                item.subject,
                f"{item.volume_af:.2f}" if item.volume_af is not None else "-",
                str(item.amount) if item.amount is not None else "-",
                f"reverses {item.reverses:05d}" if item.reverses is not None else item.note,
            ]
            for item in self.entries
        ]

    def summary(self) -> list[tuple[str, str]]:
        return [
            ("entries", str(len(self.entries))),
            ("subject", self.subject if self.subject is not None else "everything"),
            ("kind", self.kind.value if self.kind is not None else "everything"),
            ("water", f"{self.volume_af:.2f} acre feet"),
            ("money", str(self.amount)),
            ("reversals", str(len(self.reversals))),
        ]


def build(
    entries: tuple[Entry, ...],
    subject: str | None = None,
    kind: EntryKind | None = None,
    first: datetime | None = None,
    last: datetime | None = None,
) -> LedgerReport:
    """Cut the journal down to what was asked for, in sequence."""

    if first is not None and last is not None and last <= first:
        raise PolicyError("a journal report needs a span that ends after it starts")
    found = list(entries)
    if subject is not None:
        found = [item for item in found if item.subject == subject]
    if kind is not None:
        found = [item for item in found if item.kind is kind]
    if first is not None:
        found = [item for item in found if item.recorded_at >= first]
    if last is not None:
        found = [item for item in found if item.recorded_at < last]
    return LedgerReport(
        entries=tuple(sorted(found, key=lambda item: item.sequence)),
        subject=subject,
        kind=kind,
    )
