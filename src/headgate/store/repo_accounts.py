"""Reading and writing the stock book and the place of use.

Certificates are append only in the domain and they are append only here. A
transfer writes a retirement date on one row and inserts another; nothing
deletes a certificate, because the register has to be able to answer what
somebody held in a season that has already been billed.
"""

from __future__ import annotations

import sqlite3
from datetime import date
from decimal import Decimal

from ..errors import NotFoundError
from ..ids import AccountNumber, TurnoutCode
from ..model.account import Account, AccountStatus, ShareCertificate, ShareRegister
from ..model.parcel import Application, CropCode, Parcel, PlaceOfUse
from .db import one, query, transaction
from .serial import (
    date_text,
    decimal_text,
    enum_text,
    int_value,
    lines_text,
    optional_date,
    optional_date_text,
    text_date,
    text_decimal,
    text_enum,
    text_lines,
    text_value,
)

ACCOUNT_COLUMNS = "number, name, joined, status, mailing"
CERTIFICATE_COLUMNS = "serial, account_number, shares, turnout_code, issued, retired"
PARCEL_COLUMNS = (
    "parcel_id, account_number, turnout_code, irrigated_acres, crop, application, dried_up_on"
)


def save_account(connection: sqlite3.Connection, account: Account) -> None:
    """Write an account, replacing what stood under that number."""

    with transaction(connection):
        connection.execute(
            f"INSERT INTO account ({ACCOUNT_COLUMNS}) VALUES (?, ?, ?, ?, ?)"
            " ON CONFLICT (number) DO UPDATE SET"
            " name = excluded.name, joined = excluded.joined,"
            " status = excluded.status, mailing = excluded.mailing",
            (
                account.number.number,
                account.name,
                date_text(account.joined),
                enum_text(account.status),
                lines_text(account.mailing),
            ),
        )


def load_account(connection: sqlite3.Connection, number: AccountNumber) -> Account:
    row = one(
        connection,
        f"SELECT {ACCOUNT_COLUMNS} FROM account WHERE number = ?",
        (number.number,),
    )
    if row is None:
        raise NotFoundError("account", str(number))
    return _account_from(row)


def _account_from(row: sqlite3.Row) -> Account:
    return Account(
        number=AccountNumber(int_value(row["number"], "account.number")),
        name=text_value(row["name"], "account.name"),
        joined=text_date(row["joined"], "account.joined"),
        status=text_enum(AccountStatus, row["status"], "account.status"),
        mailing=text_lines(row["mailing"], "account.mailing"),
    )


def _certificate_from(row: sqlite3.Row) -> ShareCertificate:
    return ShareCertificate(
        serial=text_value(row["serial"], "certificate.serial"),
        account=AccountNumber(int_value(row["account_number"], "certificate.account_number")),
        shares=text_decimal(row["shares"], "certificate.shares"),
        turnout=TurnoutCode(text_value(row["turnout_code"], "certificate.turnout_code")),
        issued=text_date(row["issued"], "certificate.issued"),
        retired=optional_date(row["retired"], "certificate.retired"),
    )


def save_certificate(connection: sqlite3.Connection, certificate: ShareCertificate) -> None:
    """Write a certificate, or update the retirement date on one that stands."""

    with transaction(connection):
        connection.execute(
            f"INSERT INTO certificate ({CERTIFICATE_COLUMNS}) VALUES (?, ?, ?, ?, ?, ?)"
            " ON CONFLICT (serial) DO UPDATE SET retired = excluded.retired",
            (
                certificate.serial,
                certificate.account.number,
                decimal_text(certificate.shares),
                str(certificate.turnout),
                date_text(certificate.issued),
                optional_date_text(certificate.retired),
            ),
        )


def save_register(connection: sqlite3.Connection, register: ShareRegister) -> None:
    """Write the whole stock book, accounts first."""

    for account in register.accounts:
        save_account(connection, account)
    for certificate in register.certificates:
        save_certificate(connection, certificate)


def load_register(connection: sqlite3.Connection) -> ShareRegister:
    accounts = tuple(
        _account_from(row)
        for row in query(connection, f"SELECT {ACCOUNT_COLUMNS} FROM account ORDER BY number")
    )
    certificates = tuple(
        _certificate_from(row)
        for row in query(
            connection, f"SELECT {CERTIFICATE_COLUMNS} FROM certificate ORDER BY issued, serial"
        )
    )
    return ShareRegister(accounts=accounts, certificates=certificates)


def shares_outstanding(connection: sqlite3.Connection, on: date) -> Decimal:
    """Total shares outstanding on a day, straight out of the book."""

    rows = query(
        connection,
        "SELECT shares FROM certificate WHERE issued <= ? AND (retired IS NULL OR retired > ?)",
        (date_text(on), date_text(on)),
    )
    return sum(
        (text_decimal(row["shares"], "certificate.shares") for row in rows),
        Decimal("0"),
    )


def save_parcel(connection: sqlite3.Connection, parcel: Parcel) -> None:
    with transaction(connection):
        connection.execute(
            f"INSERT INTO parcel ({PARCEL_COLUMNS}) VALUES (?, ?, ?, ?, ?, ?, ?)"
            " ON CONFLICT (parcel_id) DO UPDATE SET"
            " account_number = excluded.account_number, turnout_code = excluded.turnout_code,"
            " irrigated_acres = excluded.irrigated_acres, crop = excluded.crop,"
            " application = excluded.application, dried_up_on = excluded.dried_up_on",
            (
                parcel.parcel_id,
                parcel.account.number,
                str(parcel.turnout),
                decimal_text(parcel.irrigated_acres),
                enum_text(parcel.crop),
                enum_text(parcel.application),
                optional_date_text(parcel.dried_up_on),
            ),
        )


def load_place_of_use(
    connection: sqlite3.Connection, decreed_acres: Decimal | None = None
) -> PlaceOfUse:
    parcels = tuple(
        Parcel(
            parcel_id=text_value(row["parcel_id"], "parcel.parcel_id"),
            account=AccountNumber(int_value(row["account_number"], "parcel.account_number")),
            turnout=TurnoutCode(text_value(row["turnout_code"], "parcel.turnout_code")),
            irrigated_acres=text_decimal(row["irrigated_acres"], "parcel.irrigated_acres"),
            crop=text_enum(CropCode, row["crop"], "parcel.crop"),
            application=text_enum(Application, row["application"], "parcel.application"),
            dried_up_on=optional_date(row["dried_up_on"], "parcel.dried_up_on"),
        )
        for row in query(connection, f"SELECT {PARCEL_COLUMNS} FROM parcel ORDER BY parcel_id")
    )
    return PlaceOfUse(parcels=parcels, decreed_acres=decreed_acres)


def save_place_of_use(connection: sqlite3.Connection, place: PlaceOfUse) -> None:
    for parcel in place.parcels:
        save_parcel(connection, parcel)
