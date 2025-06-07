from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from headgate.ids import AccountNumber, TurnoutCode
from headgate.model.account import Account, AccountStatus, ShareCertificate, ShareRegister
from headgate.model.ditch import Turnout
from headgate.store.db import Database
from headgate.store.repo_accounts import save_register
from headgate.store.repo_ditch import save_system
from tests.support.district import (
    TURNOUT,
    cipolletti,
    foreign_keys_off,
    init_book,
    lateral,
    run,
    shareholders,
    stock,
)

SECOND = TurnoutCode("L2-20")


@pytest.fixture
def district(tmp_path: Path) -> Path:
    return stock(
        init_book(tmp_path / "district.sqlite3"),
        lateral(),
        shareholders(),
        devices=(cipolletti(),),
    )


def test_a_tidy_book_checks_out(district: Path) -> None:
    code, output = run(district, ["check", "--on", "2025-06-01"])
    assert code == 0
    assert "nothing wrong with the book" in output
    assert "at version" in output


def test_a_turnout_with_no_device_fails_the_check(district: Path) -> None:
    with Database(district).open() as connection, foreign_keys_off(connection):
        save_system(
            connection,
            lateral(
                (
                    Turnout(TURNOUT, "Lower gate", Decimal("5280"), Decimal("6"), Decimal("40")),
                    Turnout(SECOND, "Tail gate", Decimal("9000"), Decimal("4"), Decimal("25")),
                )
            ),
        )
    code, output = run(district, ["check", "--on", "2025-06-01"])
    assert code != 0
    assert "turnout_without_device" in output
    assert "problems" in output


def test_warnings_alone_do_not_fail_the_check(district: Path) -> None:
    code, output = run(district, ["check", "--on", "2027-06-01"])
    assert code == 0
    assert "lapsed_calibration" in output


def test_the_warnings_can_be_left_off(district: Path) -> None:
    code, output = run(district, ["check", "--on", "2027-06-01", "--no-warnings"])
    assert code == 0
    assert "lapsed_calibration" not in output


def test_the_checks_can_be_listed(district: Path) -> None:
    code, output = run(district, ["check", "--list-checks"])
    assert code == 0
    assert "orphan_reading" in output
    assert "at version" not in output


def test_a_book_that_has_never_been_migrated_fails_the_check(tmp_path: Path) -> None:
    code, output = run(tmp_path / "fresh.sqlite3", ["check"])
    assert code != 0
    assert "migrations have not been run" in output


def test_a_closed_account_holding_shares_is_only_a_warning(district: Path) -> None:
    with Database(district).open() as connection:
        save_register(
            connection,
            ShareRegister(
                accounts=(
                    Account(
                        AccountNumber(118), "Alma Peterson", date(1994, 3, 1), AccountStatus.CLOSED
                    ),
                ),
                certificates=(
                    ShareCertificate(
                        "A-1001", AccountNumber(118), Decimal("20"), TURNOUT, date(2005, 4, 1)
                    ),
                ),
            ),
        )
    code, output = run(district, ["check", "--on", "2025-06-01"])
    assert code == 0
    assert "shares_on_a_closed_account" in output


def test_the_book_backs_up_and_verifies(district: Path, tmp_path: Path) -> None:
    destination = tmp_path / "backup" / "district.sqlite3"
    code, output = run(district, ["backup", str(destination)])
    assert code == 0
    assert "schema version" in output
    code, output = run(district, ["verify", str(destination)])
    assert code == 0
    assert "is sound" in output


def test_a_backup_does_not_write_over_a_copy(district: Path, tmp_path: Path) -> None:
    destination = tmp_path / "copy.sqlite3"
    run(district, ["backup", str(destination)])
    code, output = run(district, ["backup", str(destination)])
    assert code != 0
    assert "does not overwrite" in output


def test_a_file_that_is_not_a_book_does_not_verify(district: Path, tmp_path: Path) -> None:
    stray = tmp_path / "stray.sqlite3"
    stray.write_bytes(b"not a database")
    code, output = run(district, ["verify", str(stray)])
    assert code != 0


def test_a_backup_restores_into_a_fresh_book(district: Path, tmp_path: Path) -> None:
    destination = tmp_path / "copy.sqlite3"
    run(district, ["backup", str(destination)])
    restored = tmp_path / "restored.sqlite3"
    code, output = run(restored, ["restore", str(destination)])
    assert code == 0
    assert "restored to" in output
    code, output = run(restored, ["status"])
    assert "Sanpete" in output


def test_the_maintain_command_reports_the_book(district: Path) -> None:
    code, output = run(district, ["maintain"])
    assert code == 0
    assert "bytes over" in output
    assert "rows" in output


def test_the_maintain_command_can_rebuild_the_file(district: Path) -> None:
    code, output = run(district, ["maintain", "--vacuum"])
    assert code == 0
    assert "rebuilt" in output


def test_the_book_exports_as_files(district: Path, tmp_path: Path) -> None:
    bundle = tmp_path / "bundle"
    code, output = run(district, ["export", str(bundle)])
    assert code == 0
    assert "tables with" in output
    assert (bundle / "manifest.csv").exists()
    assert (bundle / "account.csv").exists()


def test_a_quiet_export_prints_only_the_summary(district: Path, tmp_path: Path) -> None:
    code, output = run(district, ["export", str(tmp_path / "bundle"), "--quiet"])
    assert code == 0
    assert "rows" in output
    assert "account:" not in output


def test_an_export_will_not_write_over_a_bundle(district: Path, tmp_path: Path) -> None:
    bundle = tmp_path / "bundle"
    run(district, ["export", str(bundle)])
    code, output = run(district, ["export", str(bundle)])
    assert code != 0
    assert "already has files" in output


def test_a_bundle_checks_out(district: Path, tmp_path: Path) -> None:
    bundle = tmp_path / "bundle"
    run(district, ["export", str(bundle)])
    code, output = run(district, ["check-bundle", str(bundle)])
    assert code == 0
    assert "matches its manifest" in output


def test_a_tampered_bundle_fails_the_check(district: Path, tmp_path: Path) -> None:
    bundle = tmp_path / "bundle"
    run(district, ["export", str(bundle)])
    (bundle / "account.csv").write_text("number,name\n", encoding="utf-8")
    code, output = run(district, ["check-bundle", str(bundle)])
    assert code != 0
    assert "does not match its checksum" in output


def test_a_command_that_changes_the_book_is_logged(district: Path) -> None:
    run(
        district,
        ["account", "add", "--number", "212", "--name", "Ruth Larsen", "--joined", "1998-05-01"],
    )
    code, output = run(district, ["log"])
    assert code == 0
    assert "account add" in output
    assert "commands logged" in output


def test_a_report_is_not_logged(district: Path) -> None:
    run(district, ["check", "--on", "2025-06-01"])
    code, output = run(district, ["log"])
    assert code == 0
    assert "check" not in output


def test_setting_the_book_up_is_logged_as_one_command(district: Path) -> None:
    code, output = run(district, ["log"])
    assert code == 0
    assert "init --name" in output


def test_a_refused_command_is_logged_as_refused(district: Path) -> None:
    run(
        district,
        ["account", "add", "--number", "212", "--name", "Ruth Larsen", "--joined", "1998-05-01"],
    )
    run(
        district,
        ["account", "add", "--number", "212", "--name", "Ruth Larsen", "--joined", "not a date"],
    )
    code, output = run(district, ["log"])
    assert code == 0
    assert "refused" in output


def test_the_log_can_be_cut_to_one_command(district: Path) -> None:
    run(
        district,
        ["account", "add", "--number", "212", "--name", "Ruth Larsen", "--joined", "1998-05-01"],
    )
    run(
        district,
        ["account", "add", "--number", "300", "--name", "Nobody", "--joined", "2001-05-01"],
    )
    code, output = run(district, ["log", "--command", "account add"])
    assert code == 0
    assert output.count("account add") == 2


def test_the_log_can_be_cut_short(district: Path) -> None:
    for number in ("212", "300", "401"):
        run(
            district,
            [
                "account",
                "add",
                "--number",
                number,
                "--name",
                f"Holder {number}",
                "--joined",
                "1998-05-01",
            ],
        )
    code, output = run(district, ["log", "--limit", "1"])
    assert code == 0
    assert output.count("account add") == 1
