"""A district the command line tests can lean on.

Every command line test needs the same skeleton: a book that has been set up, a
lateral with a turnout on it, an account holding shares, and a weir in the
turnout. Writing that four times over meant four slightly different districts
and four places to fix when a constructor gained an argument, so it lives here
once.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import date
from decimal import Decimal
from pathlib import Path

from click.testing import CliRunner

from headgate.cli.main import main
from headgate.ids import AccountNumber, DeviceTag, DitchCode, TurnoutCode
from headgate.model.account import Account, AccountStatus, ShareCertificate, ShareRegister
from headgate.model.device import Calibration, Device, DeviceKind
from headgate.model.ditch import Ditch, DitchSystem, Turnout
from headgate.store.db import Database
from headgate.store.repo_accounts import save_register
from headgate.store.repo_devices import save_device
from headgate.store.repo_ditch import save_system

LATERAL = DitchCode("L2")
TURNOUT = TurnoutCode("L2-14")
WEIR = DeviceTag("WEIR-L2-14")
HOLDER = AccountNumber(118)
SECOND_HOLDER = AccountNumber(212)
CALIBRATION = Calibration(date(2025, 4, 1), "R. Aldrich", date(2026, 4, 1))


def run(book: Path, arguments: list[str]) -> tuple[int, str]:
    """Run one command against a book and hand back the exit code and output."""

    result = CliRunner().invoke(main, ["--book", str(book), *arguments])
    return result.exit_code, result.output


def must(book: Path, arguments: list[str]) -> str:
    code, output = run(book, arguments)
    assert code == 0, f"{arguments} failed: {output}"
    return output


def init_book(path: Path, name: str = "Sanpete Ditch Company") -> Path:
    """A book that has been set up and holds nothing else."""

    must(path, ["init", "--name", name, "--state", "ut", "--stream", "Sanpete Creek"])
    return path


def lateral(turnouts: tuple[Turnout, ...] | None = None) -> DitchSystem:
    """One lateral heading on the creek, with a turnout on it."""

    gates = (
        turnouts
        if turnouts is not None
        else (Turnout(TURNOUT, "Lower gate", Decimal("5280"), Decimal("6"), Decimal("40")),)
    )
    return DitchSystem(
        ditches=(
            Ditch(
                code=LATERAL,
                name="Second Lateral",
                capacity_cfs=Decimal("12"),
                length_feet=Decimal("10560"),
                loss_fraction_per_mile=Decimal("0.05"),
                turnouts=gates,
                diversion_mile=Decimal("28.4"),
            ),
        )
    )


def shareholders(shares: str = "20", second_shares: str | None = None) -> ShareRegister:
    """One or two shareholders, delivered at the lateral's turnout."""

    accounts = [Account(HOLDER, "Alma Peterson", date(1994, 3, 1), AccountStatus.ACTIVE)]
    certificates = [ShareCertificate("A-1001", HOLDER, Decimal(shares), TURNOUT, date(2005, 4, 1))]
    if second_shares is not None:
        accounts.append(
            Account(SECOND_HOLDER, "Ruth Larsen", date(1998, 5, 1), AccountStatus.ACTIVE)
        )
        certificates.append(
            ShareCertificate(
                "A-1002", SECOND_HOLDER, Decimal(second_shares), TURNOUT, date(2005, 4, 1)
            )
        )
    return ShareRegister(accounts=tuple(accounts), certificates=tuple(certificates))


def cipolletti(turnout: TurnoutCode = TURNOUT, crest: str = "3", calibrated: bool = True) -> Device:
    """A weir in a turnout, calibrated unless the test wants it lapsed."""

    return Device(
        tag=DeviceTag(f"WEIR-{turnout}"),
        kind=DeviceKind.CIPOLLETTI_WEIR,
        installed=date(2016, 3, 1),
        crest_width_feet=Decimal(crest),
        turnout=turnout,
        calibrations=(CALIBRATION,) if calibrated else (),
    )


def open_book(path: Path) -> sqlite3.Connection:
    return Database(path).connect()


def stock(
    path: Path,
    system: DitchSystem | None = None,
    register: ShareRegister | None = None,
    devices: tuple[Device, ...] = (),
) -> Path:
    """Write a canal, a stock book and any devices into a set up book."""

    with Database(path).open() as connection:
        save_system(connection, system if system is not None else lateral())
        if register is not None:
            save_register(connection, register)
        for device in devices:
            save_device(connection, device)
    return path


@contextmanager
def foreign_keys_off(connection: sqlite3.Connection) -> Iterator[sqlite3.Connection]:
    """Let a test put the book into a state the constraints normally prevent.

    The audit checks exist for books that got into a bad state some other way:
    a restore from a backup taken mid write, a hand edit, a migration somebody
    ran with the pragma off. There is no way to reach those states through the
    repositories, which is the point of them, so a test has to turn the
    constraints off to build one.
    """

    connection.execute("PRAGMA foreign_keys = OFF")
    try:
        yield connection
    finally:
        connection.execute("PRAGMA foreign_keys = ON")
