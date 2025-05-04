from datetime import date
from decimal import Decimal

from headgate.ids import DeviceTag, TurnoutCode
from headgate.model.device import Calibration, Device, DeviceKind
from headgate.report.runsheet import build, set_point

NEAR = TurnoutCode("L2-14")
FAR = TurnoutCode("L2-20")
TODAY = date(2025, 7, 4)
CALIBRATION = Calibration(date(2025, 4, 1), "R. Aldrich", date(2026, 4, 1))


def weir(turnout: TurnoutCode = NEAR, crest: str = "3") -> Device:
    return Device(
        tag=DeviceTag(f"WEIR-{turnout}"),
        kind=DeviceKind.CIPOLLETTI_WEIR,
        installed=date(2016, 3, 1),
        crest_width_feet=Decimal(crest),
        turnout=turnout,
        calibrations=(CALIBRATION,),
    )


def meter(turnout: TurnoutCode = FAR) -> Device:
    return Device(
        tag=DeviceTag(f"METER-{turnout}"),
        kind=DeviceKind.PROPELLER_METER,
        installed=date(2016, 3, 1),
        turnout=turnout,
    )


def test_a_rate_becomes_a_gauge_height() -> None:
    point = set_point(NEAR, Decimal("2.5"), weir(), TODAY)
    assert point.is_settable
    assert point.head_feet is not None
    assert "set the staff at" in point.describe()


def test_a_turnout_with_no_device_is_set_by_eye() -> None:
    point = set_point(NEAR, Decimal("2.5"), None, TODAY)
    assert not point.is_settable
    assert "by eye" in point.note


def test_a_rate_the_structure_cannot_pass_says_so() -> None:
    point = set_point(NEAR, Decimal("40"), weir(), TODAY)
    assert not point.is_settable
    assert "outside the rated range" in point.note


def test_a_meter_is_not_set_off_a_staff() -> None:
    point = set_point(FAR, Decimal("2.5"), meter(), TODAY)
    assert not point.is_settable
    assert "totalises" in point.note or "not set off a staff" in point.note


def test_a_device_out_of_the_ditch_leaves_no_setting() -> None:
    pulled = Device(
        tag=DeviceTag("WEIR-L2-14"),
        kind=DeviceKind.CIPOLLETTI_WEIR,
        installed=date(2016, 3, 1),
        crest_width_feet=Decimal("3"),
        turnout=NEAR,
        removed=date(2025, 5, 1),
    )
    point = set_point(NEAR, Decimal("2.5"), pulled, TODAY)
    assert not point.is_settable
    assert "not in the ditch" in point.note


def test_a_sheet_is_built_in_turnout_order() -> None:
    sheet = build(
        TODAY,
        {FAR: Decimal("1.5"), NEAR: Decimal("2.5")},
        {NEAR: weir(), FAR: weir(FAR, "2")},
    )
    assert [item.turnout for item in sheet.points] == [NEAR, FAR]
    assert sheet.total_cfs == Decimal("4")


def test_a_turnout_running_nothing_is_left_off() -> None:
    sheet = build(TODAY, {NEAR: Decimal("0"), FAR: Decimal("1.5")}, {FAR: weir(FAR, "2")})
    assert [item.turnout for item in sheet.points] == [FAR]


def test_an_empty_day_says_so() -> None:
    sheet = build(TODAY, {}, {})
    assert sheet.is_empty
    assert sheet.rows() == []


def test_the_sheet_counts_what_cannot_be_set() -> None:
    sheet = build(
        TODAY, {NEAR: Decimal("40"), FAR: Decimal("1.5")}, {NEAR: weir(), FAR: weir(FAR, "2")}
    )
    assert len(sheet.unsettable) == 1
    assert dict(sheet.summary())["no setting"] == "1"


def test_the_summary_names_the_day_and_the_flow() -> None:
    sheet = build(TODAY, {NEAR: Decimal("2.5")}, {NEAR: weir()})
    summary = dict(sheet.summary())
    assert summary["day"] == "2025-07-04"
    assert "cfs" in summary["running"]


def test_the_rows_print_a_dash_where_there_is_no_setting() -> None:
    sheet = build(TODAY, {NEAR: Decimal("2.5")}, {})
    assert sheet.rows()[0][3] == "-"
    assert sheet.rows()[0][2] == "-"
