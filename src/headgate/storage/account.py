"""Whose water is in the reservoir, and what happens to it.

The pool is one body of water and it is owned in pieces. Each shareholder is
allocated a share of whatever was stored, draws against it through the season,
and carries what is left into next year up to a cap.

Two rules make this harder than a bank account and both are in here.

Spill is nobody's fault and everybody's loss. When the reservoir goes over the
top the water that leaves came out of the accounts in proportion to what was in
them, because the alternative is a rule that says the last man to store loses,
and this district has never been willing to write that down.

Carryover is capped per account, not on the pool. An account over its cap loses
the difference at the end of the water year whether or not the reservoir is
full, which is the thing that makes shareholders actually use their water.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, replace
from decimal import Decimal

from ..errors import NotFoundError, PolicyError, ValidationError
from ..ids import AccountNumber
from ..units import round_volume


@dataclass(frozen=True, slots=True)
class StorageEntry:
    """One shareholder's storage for one year."""

    account: AccountNumber
    shares: Decimal
    allocated_af: Decimal
    released_af: Decimal = Decimal("0")
    spilled_af: Decimal = Decimal("0")
    carried_in_af: Decimal = Decimal("0")

    def __post_init__(self) -> None:
        if self.shares <= 0:
            raise ValidationError(f"account {self.account} holds no shares of the reservoir")
        for name, value in (
            ("allocated", self.allocated_af),
            ("released", self.released_af),
            ("spilled", self.spilled_af),
            ("carried in", self.carried_in_af),
        ):
            if value < 0:
                raise ValidationError(f"account {self.account} has a negative {name} volume")

    @property
    def credited_af(self) -> Decimal:
        return round_volume(self.allocated_af + self.carried_in_af)

    @property
    def balance_af(self) -> Decimal:
        left = self.credited_af - self.released_af - self.spilled_af
        return round_volume(left) if left > 0 else Decimal("0")


@dataclass(frozen=True, slots=True)
class StorageBook:
    """Every storage account for one water year."""

    water_year: int
    entries: tuple[StorageEntry, ...]

    def __post_init__(self) -> None:
        seen: set[AccountNumber] = set()
        for entry in self.entries:
            if entry.account in seen:
                raise ValidationError(f"account {entry.account} has two storage entries")
            seen.add(entry.account)

    @property
    def total_balance_af(self) -> Decimal:
        return round_volume(sum((entry.balance_af for entry in self.entries), Decimal("0")))

    @property
    def total_allocated_af(self) -> Decimal:
        return round_volume(sum((entry.allocated_af for entry in self.entries), Decimal("0")))

    @property
    def accounts(self) -> tuple[AccountNumber, ...]:
        return tuple(sorted(entry.account for entry in self.entries))

    def entry_for(self, account: AccountNumber) -> StorageEntry:
        for entry in self.entries:
            if entry.account == account:
                return entry
        raise NotFoundError("storage account", str(account))

    def balance_of(self, account: AccountNumber) -> Decimal:
        return self.entry_for(account).balance_af

    def _replace_entry(self, entry: StorageEntry) -> StorageBook:
        return replace(
            self,
            entries=tuple(
                entry if item.account == entry.account else item for item in self.entries
            ),
        )

    def release_to(self, account: AccountNumber, volume_af: Decimal) -> StorageBook:
        """Draw against an account, refusing to overdraw it."""

        if volume_af < 0:
            raise ValidationError("a release may not be negative")
        entry = self.entry_for(account)
        if volume_af > entry.balance_af:
            raise PolicyError(
                f"account {account} has {entry.balance_af} acre feet stored and asked for "
                f"{volume_af}"
            )
        return self._replace_entry(
            replace(entry, released_af=round_volume(entry.released_af + volume_af))
        )

    def spill(self, volume_af: Decimal) -> StorageBook:
        """Take a spill out of every account in proportion to its balance."""

        if volume_af < 0:
            raise ValidationError("a spill may not be negative")
        held = self.total_balance_af
        if volume_af > held:
            raise PolicyError(
                f"the reservoir spilled {volume_af} acre feet and only {held} were in accounts"
            )
        if held <= 0:
            return self
        taken = Decimal("0")
        updated: list[StorageEntry] = []
        ordered = sorted(self.entries, key=lambda item: str(item.account))
        for index, entry in enumerate(ordered):
            if index == len(ordered) - 1:
                share = round_volume(volume_af - taken)
            else:
                share = round_volume(volume_af * entry.balance_af / held)
                taken += share
            updated.append(replace(entry, spilled_af=round_volume(entry.spilled_af + share)))
        return replace(self, entries=tuple(updated))

    def carry_over(self, next_water_year: int, cap_af: Decimal | None = None) -> StorageBook:
        """Roll balances into next year, losing anything over the cap."""

        if next_water_year <= self.water_year:
            raise PolicyError(f"{next_water_year} does not come after {self.water_year}")
        entries = tuple(
            StorageEntry(
                account=entry.account,
                shares=entry.shares,
                allocated_af=Decimal("0"),
                carried_in_af=entry.balance_af if cap_af is None else min(entry.balance_af, cap_af),
            )
            for entry in self.entries
        )
        return StorageBook(water_year=next_water_year, entries=entries)


def allocate(
    water_year: int,
    usable_af: Decimal,
    shares: Mapping[AccountNumber, Decimal],
    carried_in: Mapping[AccountNumber, Decimal] | None = None,
) -> StorageBook:
    """Split what is in the pool between the shareholders, by shares."""

    if usable_af < 0:
        raise ValidationError("a reservoir cannot allocate a negative volume")
    if not shares:
        raise PolicyError("nobody holds shares of the reservoir")
    total_shares = sum(shares.values(), Decimal("0"))
    if total_shares <= 0:
        raise PolicyError("the reservoir shares add up to nothing")
    carried = carried_in or {}
    ordered = sorted(shares, key=str)
    given = Decimal("0")
    entries: list[StorageEntry] = []
    for index, account in enumerate(ordered):
        if index == len(ordered) - 1:
            piece = round_volume(usable_af - given)
        else:
            piece = round_volume(usable_af * shares[account] / total_shares)
            given += piece
        entries.append(
            StorageEntry(
                account=account,
                shares=shares[account],
                allocated_af=piece,
                carried_in_af=carried.get(account, Decimal("0")),
            )
        )
    return StorageBook(water_year=water_year, entries=tuple(entries))
