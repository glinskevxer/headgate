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


class RatingError(HeadgateError):
    """A gauge height could not be turned into a flow."""


class HeadOutOfRangeError(RatingError):
    """The staff was read outside the range the rating was built for.

    This is not a malformed input. The number is real and somebody wrote it in
    the book; it is the rating that has nothing to say about it, and the record
    that comes out is an estimate rather than a measurement.
    """

    def __init__(self, head_feet: object, low: object, high: object) -> None:
        super().__init__(f"head {head_feet} ft is outside the rated range {low} to {high} ft")
        self.head_feet = head_feet
        self.low = low
        self.high = high
