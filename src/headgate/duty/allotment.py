"""The allotment: how much water a share is worth this year.

In a full year a share is worth whatever the ditch can carry and nobody counts.
In a short year the board sets an allotment in acre feet a share, and the
office counts every acre foot against it.

Two rules make an allotment survive contact with a season.

It can be revised, and a revision never claws back water that has already been
delivered. An account that used its whole allotment in June and then sees the
allotment cut in July is at zero, not in debt. What it is not allowed to do is
take more.

And it cannot be raised late. Water somebody was told he could not have is
water he did not plant on, and a district that hands it back in August after
the crop is short has not done him any favours. The board can raise the
allotment until the cut off and after that it can only be cut.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, replace
from datetime import date
from decimal import Decimal

from ..errors import NotFoundError, PolicyError, ValidationError
from ..ids import AccountNumber
from ..units import round_volume

DEFAULT_RAISE_CUTOFF = (7, 15)


@dataclass(frozen=True, slots=True)
class Allotment:
    """What the board said a share is worth, and when it said it."""

    water_year: int
    af_per_share: Decimal
    set_on: date
    basis: str
    revision: int = 0

    def __post_init__(self) -> None:
        if self.af_per_share < 0:
            raise ValidationError("a share cannot be worth less than nothing")
        if not self.basis.strip():
            raise ValidationError("an allotment says what it was worked out from")
        if self.revision < 0:
            raise ValidationError("an allotment revision counts up")

    def for_shares(self, shares: Decimal) -> Decimal:
        if shares < 0:
            raise ValidationError("a negative shareholding has no allotment")
        return round_volume(self.af_per_share * shares)

    @property
    def is_open(self) -> bool:
        """A district that is not rationing sets no allotment at all."""

        return self.af_per_share == 0

    def revise(
        self,
        af_per_share: Decimal,
        on: date,
        basis: str,
        raise_cutoff: tuple[int, int] = DEFAULT_RAISE_CUTOFF,
    ) -> Allotment:
        """Change the allotment, within the rule about raising it late."""

        if af_per_share < 0:
            raise ValidationError("a share cannot be worth less than nothing")
        if on < self.set_on:
            raise PolicyError(f"the allotment was set {self.set_on} and cannot be revised on {on}")
        cutoff = date(self.water_year, *raise_cutoff)
        if af_per_share > self.af_per_share and on > cutoff:
            raise PolicyError(f"the allotment may not be raised after {cutoff}, and it is {on}")
        return replace(
            self,
            af_per_share=af_per_share,
            set_on=on,
            basis=basis,
            revision=self.revision + 1,
        )


@dataclass(frozen=True, slots=True)
class AllotmentUse:
    """One account, against its allotment."""

    account: AccountNumber
    shares: Decimal
    used_af: Decimal

    def __post_init__(self) -> None:
        if self.used_af < 0:
            raise ValidationError(f"account {self.account} has used a negative volume")


@dataclass(frozen=True, slots=True)
class AllotmentLedger:
    """Every account against the allotment that stands today."""

    allotment: Allotment
    uses: tuple[AllotmentUse, ...]

    def __post_init__(self) -> None:
        seen: set[AccountNumber] = set()
        for use in self.uses:
            if use.account in seen:
                raise ValidationError(f"account {use.account} is on the ledger twice")
            seen.add(use.account)

    def use_for(self, account: AccountNumber) -> AllotmentUse:
        for use in self.uses:
            if use.account == account:
                return use
        raise NotFoundError("allotment account", str(account))

    def allowed_af(self, account: AccountNumber) -> Decimal:
        return self.allotment.for_shares(self.use_for(account).shares)

    def remaining_af(self, account: AccountNumber) -> Decimal:
        left = self.allowed_af(account) - self.use_for(account).used_af
        return round_volume(left) if left > 0 else Decimal("0")

    def is_over(self, account: AccountNumber) -> bool:
        return self.use_for(account).used_af > self.allowed_af(account)

    def over_by(self, account: AccountNumber) -> Decimal:
        over = self.use_for(account).used_af - self.allowed_af(account)
        return round_volume(over) if over > 0 else Decimal("0")

    @property
    def overdrawn(self) -> tuple[AllotmentUse, ...]:
        return tuple(use for use in self.uses if self.is_over(use.account))

    def take(self, account: AccountNumber, volume_af: Decimal) -> AllotmentLedger:
        """Post a delivery against an account, refusing to overdraw it."""

        if volume_af < 0:
            raise ValidationError("a delivery may not be negative")
        use = self.use_for(account)
        if volume_af > self.remaining_af(account):
            raise PolicyError(
                f"account {account} has {self.remaining_af(account)} acre feet of its "
                f"allotment left and asked for {volume_af}"
            )
        updated = replace(use, used_af=round_volume(use.used_af + volume_af))
        return replace(
            self,
            uses=tuple(updated if item.account == account else item for item in self.uses),
        )

    def under(self, allotment: Allotment) -> AllotmentLedger:
        """Put the same use against a revised allotment."""

        if allotment.water_year != self.allotment.water_year:
            raise PolicyError(
                f"a {allotment.water_year} allotment cannot be applied to "
                f"{self.allotment.water_year}"
            )
        return replace(self, allotment=allotment)


def allot(
    water_year: int,
    available_af: Decimal,
    shares: Mapping[AccountNumber, Decimal],
    set_on: date,
    basis: str,
    duty_cap_af_per_share: Decimal | None = None,
) -> AllotmentLedger:
    """Work an available supply down to acre feet a share."""

    if available_af < 0:
        raise ValidationError("a district cannot allot a negative supply")
    total_shares = sum(shares.values(), Decimal("0"))
    if total_shares <= 0:
        raise PolicyError("nobody holds shares, so there is nothing to allot")
    per_share = round_volume(available_af / total_shares)
    if duty_cap_af_per_share is not None and per_share > duty_cap_af_per_share:
        per_share = duty_cap_af_per_share
    allotment = Allotment(water_year=water_year, af_per_share=per_share, set_on=set_on, basis=basis)
    return AllotmentLedger(
        allotment=allotment,
        uses=tuple(
            AllotmentUse(account=account, shares=shares[account], used_af=Decimal("0"))
            for account in sorted(shares, key=str)
        ),
    )
