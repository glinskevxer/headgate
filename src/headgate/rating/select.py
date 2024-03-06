"""Choosing the rating that belongs to a device on a day.

Two things vary with the day and both matter. The staff offset comes from
whichever calibration stood at the time, so a structure re-set in July does not
retroactively change what June's readings meant. And a device that was out of
the ditch on the day has no rating at all, which is a different answer from a
device that read badly.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from ..errors import PolicyError
from ..model.device import Device, DeviceKind
from .curve import RatingCurve
from .flume import CutthroatFlume, ParshallFlume
from .orifice import SubmergedOrifice
from .weir import ContractedRectangularWeir, cipolletti, rectangular_suppressed, v_notch_ninety


def rating_for(device: Device, day: date) -> RatingCurve:
    """The curve that converts this device's staff into cubic feet a second."""

    if not device.in_service_on(day):
        raise PolicyError(f"device {device.tag} was not in the ditch on {day}")
    if not device.kind.is_rated_on_a_staff:
        raise PolicyError(f"device {device.tag} totalises and is not read off a rating")
    offset = device.staff_offset_on(day)
    if device.kind is DeviceKind.CIPOLLETTI_WEIR:
        assert device.crest_width_feet is not None
        return cipolletti(device.crest_width_feet, offset)
    if device.kind is DeviceKind.RECTANGULAR_WEIR:
        assert device.crest_width_feet is not None
        if device.end_contractions:
            return ContractedRectangularWeir(
                crest_width_feet=device.crest_width_feet,
                head_offset_feet=offset,
                contractions=device.end_contractions,
            )
        return rectangular_suppressed(device.crest_width_feet, offset)
    if device.kind is DeviceKind.V_NOTCH_WEIR:
        return v_notch_ninety(offset)
    if device.kind is DeviceKind.PARSHALL_FLUME:
        assert device.throat_width_feet is not None
        return ParshallFlume(device.throat_width_feet, offset)
    if device.kind is DeviceKind.CUTTHROAT_FLUME:
        assert device.throat_width_feet is not None
        return CutthroatFlume(device.throat_width_feet, offset)
    assert device.throat_width_feet is not None
    assert device.opening_height_feet is not None
    return SubmergedOrifice(device.throat_width_feet, device.opening_height_feet)


def discharge_for(device: Device, day: date, head_feet: Decimal) -> Decimal:
    """What a staff reading on a device means, on the day it was taken."""

    return rating_for(device, day).discharge_cfs(head_feet)


def rated_range(device: Device, day: date) -> tuple[Decimal, Decimal]:
    """The heads the rating is willing to answer for on that day."""

    curve = rating_for(device, day)
    return curve.min_head_feet, curve.max_head_feet
