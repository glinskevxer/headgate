import sqlite3
from datetime import date, datetime
from decimal import Decimal

from headgate.ids import AccountNumber, DecreeNumber, DeviceTag, DitchCode, TurnoutCode
from headgate.model.account import Account, AccountStatus, ShareCertificate, ShareRegister
from headgate.model.device import Calibration, Device, DeviceKind
from headgate.model.ditch import Ditch, DitchSystem, Turnout
from headgate.model.reading import StaffReading
from headgate.model.right import Priority, RightKind, WaterRight
from headgate.store.audit import (
    Severity,
    audit,
    device_tags_in_findings,
    known_checks,
    problems,
    summarise,
    turnout_codes_in_findings,
)
from headgate.store.repo_accounts import save_register
from headgate.store.repo_devices import save_device
from headgate.store.repo_ditch import save_system
from headgate.store.repo_readings import save_reading
from headgate.store.repo_rights import save_right
from tests.support.district import foreign_keys_off

FIRST = TurnoutCode("L2-14")
SECOND = TurnoutCode("L2-20")
WEIR = DeviceTag("WEIR-L2-14")
TODAY = date(2025, 6, 1)
CALIBRATION = Calibration(date(2025, 4, 1), "R. Aldrich", date(2026, 4, 1))


def system(turnouts: tuple[Turnout, ...] | None = None) -> DitchSystem:
    gates = (
        turnouts
        if turnouts is not None
        else (Turnout(FIRST, "Lower gate", Decimal("5280"), Decimal("6"), Decimal("40")),)
    )
    return DitchSystem(
        ditches=(
            Ditch(
                code=DitchCode("L2"),
                name="Second Lateral",
                capacity_cfs=Decimal("12"),
                length_feet=Decimal("10560"),
                loss_fraction_per_mile=Decimal("0.05"),
                turnouts=gates,
                diversion_mile=Decimal("28.4"),
            ),
        )
    )


def weir(**overrides: object) -> Device:
    fields: dict[str, object] = {
        "tag": WEIR,
        "kind": DeviceKind.CIPOLLETTI_WEIR,
        "installed": date(2016, 3, 1),
        "crest_width_feet": Decimal("3"),
        "turnout": FIRST,
        "calibrations": (CALIBRATION,),
    }
    fields.update(overrides)
    return Device(**fields)  # type: ignore[arg-type]


def tidy(book: sqlite3.Connection) -> None:
    save_system(book, system())
    save_device(book, weir())
    save_register(
        book,
        ShareRegister(
            accounts=(
                Account(
                    AccountNumber(118), "Alma Peterson", date(1994, 3, 1), AccountStatus.ACTIVE
                ),
            ),
            certificates=(
                ShareCertificate(
                    "A-1001", AccountNumber(118), Decimal("20"), FIRST, date(2005, 4, 1)
                ),
            ),
        ),
    )


def test_a_tidy_book_has_nothing_wrong_with_it(book: sqlite3.Connection) -> None:
    tidy(book)
    assert audit(book, TODAY) == ()
    assert summarise(()) == "nothing wrong with the book"


def test_a_turnout_with_no_device_is_a_problem(book: sqlite3.Connection) -> None:
    tidy(book)
    with foreign_keys_off(book):
        save_system(
            book,
            system(
                (
                    Turnout(FIRST, "Lower gate", Decimal("5280"), Decimal("6"), Decimal("40")),
                    Turnout(SECOND, "Tail gate", Decimal("9000"), Decimal("4"), Decimal("25")),
                )
            ),
        )
    found = audit(book, TODAY)
    assert any(item.check == "turnout_without_device" for item in found)
    assert problems(found)


def test_a_lapsed_calibration_is_only_a_warning(book: sqlite3.Connection) -> None:
    tidy(book)
    found = audit(book, date(2027, 6, 1))
    lapsed = [item for item in found if item.check == "lapsed_calibration"]
    assert lapsed
    assert lapsed[0].severity is Severity.WARNING
    assert not lapsed[0].severity.stops_the_season


def test_a_reading_after_the_device_came_out_is_a_problem(book: sqlite3.Connection) -> None:
    tidy(book)
    save_reading(
        book,
        StaffReading(
            device=WEIR,
            taken_at=datetime(2025, 7, 1, 6),
            observer="D. Yardley",
            head_feet=Decimal("0.62"),
        ),
    )
    save_device(book, weir(removed=date(2025, 6, 15)))
    found = audit(book, TODAY)
    assert any(item.check == "reading_after_removal" for item in found)


def test_a_reading_against_a_device_that_is_not_in_the_book_is_found(
    book: sqlite3.Connection,
) -> None:
    tidy(book)
    with foreign_keys_off(book):
        book.execute(
            "INSERT INTO reading (device_tag, taken_at, observer, method, head_feet)"
            " VALUES ('WEIR-L2-99', '2025-06-01 06:00:00', 'D. Yardley', 'staff', '0.5')"
        )
    found = audit(book, TODAY)
    assert any(item.check == "orphan_reading" for item in found)


def test_a_certificate_at_a_turnout_that_was_removed_is_found(
    book: sqlite3.Connection,
) -> None:
    tidy(book)
    with foreign_keys_off(book):
        save_system(
            book,
            system((Turnout(SECOND, "Tail gate", Decimal("9000"), Decimal("4"), Decimal("25")),)),
        )
    found = audit(book, TODAY)
    assert any(item.check == "certificate_off_the_system" for item in found)


def test_a_right_decreed_to_a_ditch_that_is_gone_is_found(book: sqlite3.Connection) -> None:
    tidy(book)
    with foreign_keys_off(book):
        save_right(
            book,
            WaterRight(
                decree=DecreeNumber("CDA-1920-4"),
                owner="Alma Peterson",
                kind=RightKind.DIRECT_FLOW,
                priority=Priority(date(1889, 5, 1), 1920, 4),
                diversion_mile=Decimal("28.4"),
                rate_cfs=Decimal("4"),
                ditch=DitchCode("L9"),
            ),
        )
    found = audit(book, TODAY)
    assert any(item.check == "right_off_the_system" for item in found)


def test_shares_on_a_closed_account_are_a_warning(book: sqlite3.Connection) -> None:
    tidy(book)
    save_register(
        book,
        ShareRegister(
            accounts=(
                Account(
                    AccountNumber(118), "Alma Peterson", date(1994, 3, 1), AccountStatus.CLOSED
                ),
            ),
            certificates=(
                ShareCertificate(
                    "A-1001", AccountNumber(118), Decimal("20"), FIRST, date(2005, 4, 1)
                ),
            ),
        ),
    )
    found = audit(book, TODAY)
    assert any(item.check == "shares_on_a_closed_account" for item in found)


def test_a_finding_describes_itself(book: sqlite3.Connection) -> None:
    tidy(book)
    found = audit(book, date(2027, 6, 1))
    assert "warning:" in found[0].describe()


def test_the_summary_counts_problems_and_warnings(book: sqlite3.Connection) -> None:
    tidy(book)
    found = audit(book, date(2027, 6, 1))
    assert "warnings" in summarise(found)


def test_every_check_has_a_name(book: sqlite3.Connection) -> None:
    tidy(book)
    found = audit(book, date(2027, 6, 1))
    for item in found:
        assert item.check in known_checks()


def test_the_subjects_that_are_codes_can_be_picked_out(book: sqlite3.Connection) -> None:
    tidy(book)
    found = audit(book, date(2027, 6, 1))
    assert device_tags_in_findings(found)
    assert turnout_codes_in_findings(found) == ()


def test_a_device_installed_at_a_turnout_that_is_gone_is_found(
    book: sqlite3.Connection,
) -> None:
    tidy(book)
    with foreign_keys_off(book):
        save_system(
            book,
            system((Turnout(SECOND, "Tail gate", Decimal("9000"), Decimal("4"), Decimal("25")),)),
        )
    found = audit(book, TODAY)
    assert any(item.check == "device_off_the_system" for item in found)


def test_water_ordered_at_a_turnout_that_is_gone_is_counted(
    book: sqlite3.Connection,
) -> None:
    from headgate.store.audit import unchecked_volume

    tidy(book)
    assert unchecked_volume(book) == Decimal("0")
    with foreign_keys_off(book):
        book.execute(
            "INSERT INTO water_order (order_id, account_number, turnout_code, requested_cfs,"
            " run_from, run_to, placed_at, status, allowed_cfs)"
            " VALUES (1, 118, 'L2-99', '3', '2025-07-01 06:00:00', '2025-07-08 06:00:00',"
            " '2025-06-28 08:00:00', 'accepted', '3')"
        )
    assert unchecked_volume(book) > Decimal("0")


def test_a_problem_stops_the_season_and_a_warning_does_not() -> None:
    assert Severity.PROBLEM.stops_the_season
    assert not Severity.WARNING.stops_the_season
