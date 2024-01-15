"""The error hierarchy.

Every failure the package raises on purpose is a HeadgateError. Anything else
reaching a caller is a bug, and the command line layer is allowed to treat it
that way.
"""

from __future__ import annotations


class HeadgateError(Exception):
    """Base for every deliberate failure in the package."""


class ValidationError(HeadgateError):
    """A value did not satisfy a rule that is checked at the boundary."""


class NotFoundError(HeadgateError):
    """A record was asked for by identifier and does not exist."""

    def __init__(self, kind: str, key: str) -> None:
        super().__init__(f"no {kind} with identifier {key!r}")
        self.kind = kind
        self.key = key


class ConflictError(HeadgateError):
    """A record exists that forbids the write being attempted."""


class PolicyError(HeadgateError):
    """The district's own rules refuse the operation.

    Distinct from ValidationError on purpose. A validation failure means the
    input was malformed. A policy failure means the input was well formed and
    the district will not do it.
    """
