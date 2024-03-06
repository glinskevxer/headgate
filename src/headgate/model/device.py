"""Measuring devices, and whether anybody still trusts them.

Every turnout that is measured has a structure in it and a staff gauge on the
structure. What the device is decides which rating converts a gauge height into
a flow, and the calibration record decides whether the answer counts as a
measurement or as an estimate. Those are separate questions and the second one
is the one that gets forgotten.

A calibration is a dated field check with an expiry. Past the expiry the device
still reads, and the record it produces is still worth keeping, but it is not
evidence of anything.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import date
from decimal import Decimal
from enum import Enum

from ..errors import ValidationError
from ..ids import DeviceTag, DitchCode, TurnoutCode


class DeviceKind(Enum):
    """The structure in the ditch, which decides the rating that fits it."""

    CIPOLLETTI_WEIR = "cipolletti_weir"
    RECTANGULAR_WEIR = "rectangular_weir"
    V_NOTCH_WEIR = "v_notch_weir"
    PARSHALL_FLUME = "parshall_flume"
    CUTTHROAT_FLUME = "cutthroat_flume"
    SUBMERGED_ORIFICE = "submerged_orifice"
    PROPELLER_METER = "propeller_meter"

    @property
    def tag_word(self) -> str:
        if self.name.endswith("WEIR"):
            return "WEIR"
        if self.name.endswith("FLUME"):
            return "FLUME"
        if self is DeviceKind.SUBMERGED_ORIFICE:
            return "ORIFICE"
        return "METER"

    @property
    def needs_a_crest_width(self) -> bool:
        return self in {DeviceKind.CIPOLLETTI_WEIR, DeviceKind.RECTANGULAR_WEIR}

    @property
    def needs_a_throat_width(self) -> bool:
        return self in {
            DeviceKind.PARSHALL_FLUME,
            DeviceKind.CUTTHROAT_FLUME,
            DeviceKind.SUBMERGED_ORIFICE,
        }

    @property
    def needs_an_opening_height(self) -> bool:
        return self is DeviceKind.SUBMERGED_ORIFICE

    @property
    def is_rated_on_a_staff(self) -> bool:
        """A propeller meter totalises. Everything else is read off a staff."""

        return self is not DeviceKind.PROPELLER_METER


@dataclass(frozen=True, slots=True)
class Calibration:
    """A field check against a current meter, and how long it stands."""

    performed: date
    performed_by: str
    expires: date
    staff_offset_feet: Decimal = Decimal("0")
    note: str = ""

    def __post_init__(self) -> None:
        if self.expires <= self.performed:
            raise ValidationError(
                f"a calibration performed {self.performed} cannot expire {self.expires}"
            )
        if not self.performed_by.strip():
            raise ValidationError("a calibration has to say who did it")
        if abs(self.staff_offset_feet) > Decimal("0.5"):
            raise ValidationError(
                f"a staff offset of {self.staff_offset_feet} feet means the gauge was reset, "
                "not calibrated"
            )

    def covers(self, day: date) -> bool:
        return self.performed <= day < self.expires


@dataclass(frozen=True, slots=True)
class Device:
    """A structure and its staff gauge, at one site."""

    tag: DeviceTag
    kind: DeviceKind
    installed: date
    crest_width_feet: Decimal | None = None
    throat_width_feet: Decimal | None = None
    opening_height_feet: Decimal | None = None
    end_contractions: int = 0
    min_head_feet: Decimal = Decimal("0.05")
    max_head_feet: Decimal = Decimal("2.0")
    turnout: TurnoutCode | None = None
    ditch: DitchCode | None = None
    removed: date | None = None
    calibrations: tuple[Calibration, ...] = ()

    def __post_init__(self) -> None:
        if self.tag.kind_word != self.kind.tag_word:
            raise ValidationError(
                f"device {self.tag} is tagged {self.tag.kind_word} and is a {self.kind.value}"
            )
        if self.turnout is None and self.ditch is None:
            raise ValidationError(f"device {self.tag} is not installed anywhere")
        if self.turnout is not None and self.ditch is not None:
            raise ValidationError(f"device {self.tag} cannot sit at a turnout and on a ditch")
        if self.max_head_feet <= self.min_head_feet:
            raise ValidationError(f"device {self.tag} has an empty head range")
        if self.min_head_feet <= 0:
            raise ValidationError(f"device {self.tag} would read at or below zero head")
        if self.kind.needs_a_crest_width and self.crest_width_feet is None:
            raise ValidationError(f"device {self.tag} is a weir with no crest width")
        if self.crest_width_feet is not None and self.crest_width_feet <= 0:
            raise ValidationError(f"device {self.tag} has a crest width of {self.crest_width_feet}")
        if self.kind.needs_a_throat_width and self.throat_width_feet is None:
            raise ValidationError(f"device {self.tag} is a {self.kind.value} with no throat width")
        if self.throat_width_feet is not None and self.throat_width_feet <= 0:
            raise ValidationError(
                f"device {self.tag} has a throat width of {self.throat_width_feet}"
            )
        if self.kind.needs_an_opening_height and self.opening_height_feet is None:
            raise ValidationError(f"device {self.tag} is an orifice with no opening height")
        if self.end_contractions not in (0, 1, 2):
            raise ValidationError(f"device {self.tag} claims {self.end_contractions} contractions")
        if self.end_contractions and self.kind is not DeviceKind.RECTANGULAR_WEIR:
            raise ValidationError(f"device {self.tag} is not a weir that can be contracted")
        if self.removed is not None and self.removed <= self.installed:
            raise ValidationError(f"device {self.tag} was removed before it was installed")
        for earlier, later in zip(self.calibrations, self.calibrations[1:], strict=False):
            if later.performed < earlier.performed:
                raise ValidationError(f"device {self.tag} lists its calibrations out of order")

    @property
    def site(self) -> str:
        return str(self.turnout) if self.turnout is not None else str(self.ditch)

    def in_service_on(self, day: date) -> bool:
        if day < self.installed:
            return False
        return self.removed is None or day < self.removed

    def calibration_on(self, day: date) -> Calibration | None:
        """The calibration that stands on a day, if one does."""

        current: Calibration | None = None
        for calibration in self.calibrations:
            if calibration.covers(day):
                current = calibration
        return current

    def is_calibrated_on(self, day: date) -> bool:
        return self.calibration_on(day) is not None

    def staff_offset_on(self, day: date) -> Decimal:
        calibration = self.calibration_on(day)
        return calibration.staff_offset_feet if calibration is not None else Decimal("0")

    def head_in_range(self, head_feet: Decimal) -> bool:
        return self.min_head_feet <= head_feet <= self.max_head_feet

    def with_calibration(self, calibration: Calibration) -> Device:
        ordered = tuple(sorted((*self.calibrations, calibration), key=lambda item: item.performed))
        return replace(self, calibrations=ordered)
