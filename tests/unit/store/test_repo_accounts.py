import sqlite3
from datetime import date
from decimal import Decimal

import pytest

from headgate.errors import NotFoundError
from headgate.ids import AccountNumber, DitchCode, TurnoutCode
from headgate.model.account import Account, AccountStatus, ShareCertificate, ShareRegister
from headgate.model.ditch import Ditch, DitchSystem, Turnout
from headgate.model.parcel import Application, CropCode, Parcel, PlaceOfUse
from headgate.store.repo_accounts import (
    load_account,
    load_place_of_use,
    load_register,
    save_account,
    save_certificate,
    save_place_of_use,
    save_register,
    shares_outstanding,
)
from headgate.store.repo_ditch import save_system


def system() -> DitchSystem:
    return DitchSystem(
        ditches=(
            Ditch(
                code=DitchCode("L2"),
                name="Second Lateral",
                capacity_cfs=Decimal("12"),
                length_feet=Decimal("10560"),
                loss_fraction_per_mile=Decimal("0.04"),
                turnouts=(
                    Turnout(
                        TurnoutCode("L2-14"),
                        "Bench gate",
                        Decimal("5280"),
                        Decimal("3"),
                        Decimal("40"),
                    ),
                    Turnout(
                        TurnoutCode("L2-20"),
                        "Lower gate",
                        Decimal("9000"),
                        Decimal("3"),
                        Decimal("60"),
                    ),
                ),
                diversion_mile=Decimal("28.4"),
            ),
        )
    )


def account(number: int, status: AccountStatus = AccountStatus.ACTIVE) -> Account:
    return Account(
        number=AccountNumber(number),
        name=f"Holder {number}",
        joined=date(1994, 3, 1),
        status=status,
        mailing=("Box 41", "Manti UT 84642"),
    )


def certificate(
    serial: str, number: int, shares: str, retired: date | None = None
) -> ShareCertificate:
    return ShareCertificate(
        serial=serial,
        account=AccountNumber(number),
        shares=Decimal(shares),
        turnout=TurnoutCode("L2-14"),
        issued=date(2020, 4, 1),
        retired=retired,
    )


def register() -> ShareRegister:
    return ShareRegister(
        accounts=(account(118), account(212, AccountStatus.SUSPENDED)),
        certificates=(certificate("A-1001", 118, "12"), certificate("A-1002", 212, "4")),
    )


def stocked(book: sqlite3.Connection) -> None:
    save_system(book, system())
    save_register(book, register())


def test_an_account_comes_back_with_its_address(book: sqlite3.Connection) -> None:
    save_account(book, account(118))
    loaded = load_account(book, AccountNumber(118))
    assert loaded == account(118)
    assert loaded.mailing == ("Box 41", "Manti UT 84642")


def test_saving_an_account_twice_updates_it(book: sqlite3.Connection) -> None:
    save_account(book, account(118))
    save_account(book, account(118, AccountStatus.CLOSED))
    assert load_account(book, AccountNumber(118)).status is AccountStatus.CLOSED


def test_an_account_that_is_not_there_is_reported_missing(book: sqlite3.Connection) -> None:
    with pytest.raises(NotFoundError, match="no account"):
        load_account(book, AccountNumber(999))


def test_the_register_comes_back_whole(book: sqlite3.Connection) -> None:
    stocked(book)
    loaded = load_register(book)
    assert loaded.total_shares(date(2024, 6, 1)) == Decimal("16")
    assert loaded.account(AccountNumber(212)).status is AccountStatus.SUSPENDED


def test_a_certificate_needs_an_account_and_a_turnout(book: sqlite3.Connection) -> None:
    save_system(book, system())
    with pytest.raises(sqlite3.IntegrityError):
        save_certificate(book, certificate("A-1001", 118, "12"))


def test_retiring_a_certificate_updates_the_row(book: sqlite3.Connection) -> None:
    stocked(book)
    save_certificate(book, certificate("A-1001", 118, "12", retired=date(2024, 7, 1)))
    loaded = load_register(book)
    assert loaded.shares_of(AccountNumber(118), date(2024, 8, 1)) == Decimal("0")


def test_shares_outstanding_answers_as_of_a_day(book: sqlite3.Connection) -> None:
    stocked(book)
    save_certificate(book, certificate("A-1001", 118, "12", retired=date(2024, 7, 1)))
    assert shares_outstanding(book, date(2024, 6, 1)) == Decimal("16")
    assert shares_outstanding(book, date(2024, 8, 1)) == Decimal("4")


def test_a_place_of_use_comes_back_parcel_by_parcel(book: sqlite3.Connection) -> None:
    stocked(book)
    place = PlaceOfUse(
        parcels=(
            Parcel(
                "11-042-001",
                AccountNumber(118),
                TurnoutCode("L2-14"),
                Decimal("40"),
                CropCode.ALFALFA,
            ),
            Parcel(
                "11-042-002",
                AccountNumber(212),
                TurnoutCode("L2-20"),
                Decimal("22.5"),
                CropCode.PASTURE,
            ),
        ),
        decreed_acres=Decimal("120"),
    )
    save_place_of_use(book, place)
    loaded = load_place_of_use(book, Decimal("120"))
    assert loaded == place


def test_drying_up_a_parcel_is_written_back(book: sqlite3.Connection) -> None:
    stocked(book)
    place = PlaceOfUse(
        parcels=(
            Parcel(
                "11-042-001",
                AccountNumber(118),
                TurnoutCode("L2-14"),
                Decimal("40"),
                CropCode.ALFALFA,
            ),
        )
    )
    save_place_of_use(book, place)
    save_place_of_use(book, place.dry_up("11-042-001", date(2024, 7, 1)))
    loaded = load_place_of_use(book)
    assert loaded.acres_on(date(2024, 8, 1)) == Decimal("0")
    assert loaded.parcel("11-042-001").crop is CropCode.FALLOW


def test_an_empty_book_has_an_empty_place_of_use(book: sqlite3.Connection) -> None:
    assert load_place_of_use(book).parcels == ()


def test_a_parcel_keeps_how_the_water_is_put_on_it(book: sqlite3.Connection) -> None:
    stocked(book)
    place = PlaceOfUse(
        parcels=(
            Parcel(
                "11-042-001",
                AccountNumber(118),
                TurnoutCode("L2-14"),
                Decimal("40"),
                CropCode.ALFALFA,
                Application.PIVOT,
            ),
        )
    )
    save_place_of_use(book, place)
    loaded = load_place_of_use(book)
    assert loaded.parcel("11-042-001").application is Application.PIVOT


def test_a_parcel_written_before_the_column_existed_reads_as_flood(
    book: sqlite3.Connection,
) -> None:
    stocked(book)
    book.execute(
        "INSERT INTO parcel (parcel_id, account_number, turnout_code, irrigated_acres, crop)"
        " VALUES ('11-042-009', 118, 'L2-14', '20', 'pasture')"
    )
    assert load_place_of_use(book).parcel("11-042-009").application is Application.FLOOD
