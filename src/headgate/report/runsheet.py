"""The rider's run sheet: what to set, where, and to what.

A ditch rider leaves at six with a sheet of paper. Every line on it is a
turnout, the rate it is supposed to run at today, and the gauge height that
gives that rate on whatever structure is in that gate. The last part is the
whole reason this is worth printing: telling a rider to set two and a half
cubic feet a second is useless, and telling him to set the staff at seven
tenths is an instruction he can follow.

A turnout whose rate falls outside its structure's rating gets a line saying
so rather than a number, because a rider who is handed an impossible setting
will set something, and it will be wrong.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from ..errors import HeadgateError
from ..ids import DeviceTag, TurnoutCode
from ..model.device import Device
from ..rating.select import rating_for
from ..units import round_rate


@dataclass(frozen=True, slots=True)
class SetPoint:
    """One turnout on the sheet."""

    turnout: TurnoutCode
    rate_cfs: Decimal
    device: DeviceTag | None
    head_feet: Decimal | None
    note: str

    @property
    def is_settable(self) -> bool:
        return self.head_feet is not None

    def describe(self) -> str:
        if self.head_feet is None:
            return f"{self.turnout}: {round_rate(self.rate_cfs)} cfs, {self.note}"
        return (
            f"{self.turnout}: set the staff at {self.head_feet} ft for "
            f"{round_rate(self.rate_cfs)} cfs"
        )


@dataclass(frozen=True, slots=True)
class RunSheet:
    """A day's work, in the order a rider drives it."""

    day: date
    points: tuple[SetPoint, ...]

    @property
    def total_cfs(self) -> Decimal:
        return round_rate(sum((item.rate_cfs for item in self.points), Decimal("0")))

    @property
    def unsettable(self) -> tuple[SetPoint, ...]:
        return tuple(item for item in self.points if not item.is_settable)

    @property
    def is_empty(self) -> bool:
        return not self.points

    def rows(self) -> list[list[str]]:
        return [
            [
                str(item.turnout),
                f"{item.rate_cfs:.3f}",
                str(item.device) if item.device is not None else "-",
                f"{item.head_feet:.2f}" if item.head_feet is not None else "-",
                item.note,
            ]
            for item in self.points
        ]

    def summary(self) -> list[tuple[str, str]]:
        return [
            ("day", self.day.isoformat()),
            ("turnouts", str(len(self.points))),
            ("running", f"{self.total_cfs} cfs"),
            ("no setting", str(len(self.unsettable))),
        ]


def set_point(
    turnout: TurnoutCode, rate_cfs: Decimal, device: Device | None, day: date
) -> SetPoint:
    """Work out the gauge height that gives a rate at one turnout."""

    if device is None:
        return SetPoint(
            turnout=turnout,
            rate_cfs=rate_cfs,
            device=None,
            head_feet=None,
            note="no device in this turnout, set it by eye",
        )
    try:
        curve = rating_for(device, day)
        head = curve.head_for(rate_cfs)  # type: ignore[attr-defined]
    except HeadgateError as exc:
        return SetPoint(
            turnout=turnout,
            rate_cfs=rate_cfs,
            device=device.tag,
            head_feet=None,
            note=str(exc),
        )
    except AttributeError:
        return SetPoint(
            turnout=turnout,
            rate_cfs=rate_cfs,
            device=device.tag,
            head_feet=None,
            note="this structure is not set off a staff",
        )
    return SetPoint(
        turnout=turnout,
        rate_cfs=rate_cfs,
        device=device.tag,
        head_feet=head,
        note="",
    )


def build(
    day: date,
    wanted: dict[TurnoutCode, Decimal],
    devices: dict[TurnoutCode, Device],
) -> RunSheet:
    """Put the sheet together for a day, in turnout order."""

    points = tuple(
        set_point(turnout, wanted[turnout], devices.get(turnout), day)
        for turnout in sorted(wanted, key=str)
        if wanted[turnout] > 0
    )
    return RunSheet(day=day, points=points)
