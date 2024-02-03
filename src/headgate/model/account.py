"""Shareholders and the certificates that entitle them to water.

A share is not a volume. It is a fraction of whatever the ditch actually
diverts, so a certificate says how many shares and which turnout they are
delivered at, and the season decides what a share was worth.

Certificates are never edited. A transfer retires one and issues another, which
is what the stock book on the shelf does, and it is the only way the register
can answer what somebody held on a day two seasons ago.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, replace
from datetime import date
from decimal import Decimal
from enum import Enum

from ..errors import ConflictError, NotFoundError, PolicyError, ValidationError
from ..ids import AccountNumber, TurnoutCode

SERIAL_PATTERN = re.compile(r"^[A-Z]{1,3}-[0-9]{1,6}$")


class AccountStatus(Enum):
    """Whether the office will deliver water to this account."""

    ACTIVE = "active"
    SUSPENDED = "suspended"
    CLOSED = "closed"


@dataclass(frozen=True, slots=True)
class Account:
    """A shareholder in the ditch company."""

    number: AccountNumber
    name: str
    joined: date
    status: AccountStatus = AccountStatus.ACTIVE
    mailing: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise ValidationError(f"account {self.number} has no name on it")

    @property
    def takes_delivery(self) -> bool:
        return self.status is AccountStatus.ACTIVE


@dataclass(frozen=True, slots=True)
class ShareCertificate:
    """One certificate out of the stock book."""

    serial: str
    account: AccountNumber
    shares: Decimal
    turnout: TurnoutCode
    issued: date
    retired: date | None = None

    def __post_init__(self) -> None:
        if not SERIAL_PATTERN.match(self.serial):
            raise ValidationError(f"{self.serial!r} is not a certificate serial")
        if self.shares <= 0:
            raise ValidationError(f"certificate {self.serial} carries no shares")
        if self.retired is not None and self.retired < self.issued:
            raise ValidationError(
                f"certificate {self.serial} was retired {self.retired}, before it was issued"
            )

    def held_on(self, day: date) -> bool:
        if day < self.issued:
            return False
        return self.retired is None or day < self.retired


@dataclass(frozen=True, slots=True)
class ShareRegister:
    """The stock book, in the order the certificates were written."""

    accounts: tuple[Account, ...]
    certificates: tuple[ShareCertificate, ...] = ()

    def __post_init__(self) -> None:
        seen_numbers: set[AccountNumber] = set()
        for account in self.accounts:
            if account.number in seen_numbers:
                raise ValidationError(f"account {account.number} appears twice in the register")
            seen_numbers.add(account.number)
        seen_serials: set[str] = set()
        for certificate in self.certificates:
            if certificate.serial in seen_serials:
                raise ValidationError(f"certificate {certificate.serial} appears twice")
            seen_serials.add(certificate.serial)
            if certificate.account not in seen_numbers:
                raise ValidationError(
                    f"certificate {certificate.serial} is held by account "
                    f"{certificate.account}, which is not in the register"
                )

    def account(self, number: AccountNumber) -> Account:
        for account in self.accounts:
            if account.number == number:
                return account
        raise NotFoundError("account", str(number))

    def certificate(self, serial: str) -> ShareCertificate:
        for certificate in self.certificates:
            if certificate.serial == serial:
                return certificate
        raise NotFoundError("certificate", serial)

    def held_on(self, day: date) -> tuple[ShareCertificate, ...]:
        return tuple(item for item in self.certificates if item.held_on(day))

    def shares_of(self, number: AccountNumber, day: date) -> Decimal:
        return sum(
            (item.shares for item in self.held_on(day) if item.account == number), Decimal("0")
        )

    def shares_at(self, turnout: TurnoutCode, day: date) -> Decimal:
        return sum(
            (item.shares for item in self.held_on(day) if item.turnout == turnout), Decimal("0")
        )

    def total_shares(self, day: date) -> Decimal:
        return sum((item.shares for item in self.held_on(day)), Decimal("0"))

    def issue(self, certificate: ShareCertificate) -> ShareRegister:
        holder = self.account(certificate.account)
        if holder.status is AccountStatus.CLOSED:
            raise PolicyError(f"account {holder.number} is closed and cannot be issued shares")
        if any(item.serial == certificate.serial for item in self.certificates):
            raise ConflictError(f"certificate {certificate.serial} is already in the book")
        return replace(self, certificates=(*self.certificates, certificate))

    def transfer(
        self, serial: str, to_account: AccountNumber, on: date, new_serial: str
    ) -> ShareRegister:
        """Retire a certificate and write its replacement to a new holder."""

        original = self.certificate(serial)
        if not original.held_on(on):
            raise PolicyError(f"certificate {serial} was not outstanding on {on}")
        holder = self.account(to_account)
        if holder.status is AccountStatus.CLOSED:
            raise PolicyError(f"account {to_account} is closed and cannot take a transfer")
        retired = replace(original, retired=on)
        issued = ShareCertificate(
            serial=new_serial,
            account=to_account,
            shares=original.shares,
            turnout=original.turnout,
            issued=on,
        )
        kept = tuple(item for item in self.certificates if item.serial != serial)
        return replace(self, certificates=(*kept, retired, issued))
