"""Identifiers, and the shapes the office writes them in.

These are not opaque keys. A turnout code names the lateral it hangs off, a
device tag names the turnout it measures, and a decree number carries the
adjudication year. Parsing them here means the rest of the package can rely on
the relationship instead of splitting strings in a dozen places.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import ClassVar, Self

from .errors import ValidationError


@dataclass(frozen=True, slots=True, order=True)
class Code:
    """A validated upper case identifier."""

    pattern: ClassVar[re.Pattern[str]] = re.compile(r"^[A-Z0-9-]{1,32}$")
    label: ClassVar[str] = "code"
    text: str

    def __post_init__(self) -> None:
        if not self.pattern.match(self.text):
            raise ValidationError(f"{self.text!r} is not a {self.label}")

    def __str__(self) -> str:
        return self.text

    @classmethod
    def parse(cls, text: str) -> Self:
        return cls(text.strip().upper())


@dataclass(frozen=True, slots=True, order=True)
class DitchCode(Code):
    """The main canal or one of its laterals, as the map labels it."""

    pattern: ClassVar[re.Pattern[str]] = re.compile(r"^[A-Z]{1,6}[0-9]{0,3}$")
    label: ClassVar[str] = "ditch code"


@dataclass(frozen=True, slots=True, order=True)
class TurnoutCode(Code):
    """A turnout, written as the lateral it hangs off and its station number."""

    pattern: ClassVar[re.Pattern[str]] = re.compile(r"^([A-Z]{1,6}[0-9]{0,3})-([0-9]{1,3})$")
    label: ClassVar[str] = "turnout code"

    @property
    def ditch(self) -> DitchCode:
        match = self.pattern.match(self.text)
        assert match is not None
        return DitchCode(match.group(1))

    @property
    def station(self) -> int:
        match = self.pattern.match(self.text)
        assert match is not None
        return int(match.group(2))


@dataclass(frozen=True, slots=True, order=True)
class DeviceTag(Code):
    """A measuring device, tagged with its kind and the turnout it sits in."""

    pattern: ClassVar[re.Pattern[str]] = re.compile(
        r"^(WEIR|FLUME|ORIFICE|METER)-([A-Z]{1,6}[0-9]{0,3}-[0-9]{1,3}|[A-Z]{1,6}[0-9]{0,3})$"
    )
    label: ClassVar[str] = "device tag"

    @property
    def kind_word(self) -> str:
        match = self.pattern.match(self.text)
        assert match is not None
        return match.group(1)

    @property
    def site(self) -> str:
        match = self.pattern.match(self.text)
        assert match is not None
        return match.group(2)


@dataclass(frozen=True, slots=True, order=True)
class DecreeNumber(Code):
    """A decreed right, as the water court numbered it."""

    pattern: ClassVar[re.Pattern[str]] = re.compile(r"^([A-Z]{2,4})-([0-9]{4})-([0-9]{1,5})$")
    label: ClassVar[str] = "decree number"

    @property
    def district(self) -> str:
        match = self.pattern.match(self.text)
        assert match is not None
        return match.group(1)

    @property
    def adjudication_year(self) -> int:
        match = self.pattern.match(self.text)
        assert match is not None
        return int(match.group(2))

    @property
    def sequence(self) -> int:
        match = self.pattern.match(self.text)
        assert match is not None
        return int(match.group(3))


@dataclass(frozen=True, slots=True, order=True)
class AccountNumber:
    """A shareholder account, which the office says out loud as a number."""

    number: int

    def __post_init__(self) -> None:
        if self.number < 1 or self.number > 99999:
            raise ValidationError(f"account number {self.number} is outside the book")

    def __str__(self) -> str:
        return f"{self.number:05d}"

    @classmethod
    def parse(cls, text: str) -> Self:
        stripped = text.strip().lstrip("#")
        if not stripped.isdigit():
            raise ValidationError(f"{text!r} is not an account number")
        return cls(int(stripped))
