from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
from click.testing import CliRunner

from headgate.cli.main import main
from headgate.ids import AccountNumber, DitchCode, TurnoutCode
from headgate.model.account import Account, AccountStatus, ShareCertificate, ShareRegister
from headgate.model.ditch import Ditch, DitchSystem, Turnout
from headgate.store.db import Database
from headgate.store.repo_accounts import save_register
from headgate.store.repo_ditch import save_system
from headgate.store.repo_season import declare_season
from headgate.wateryear import IrrigationSeason

TURNOUT = TurnoutCode("L2-14")


@pytest.fixture
def district(tmp_path: Path) -> Path:
    book = tmp_path / "district.sqlite3"
    result = CliRunner().invoke(
        main,
        [
            "--book",
            str(book),
            "init",
            "--name",
            "Sanpete Ditch Company",
            "--state",
            "ut",
            "--stream",
            "Sanpete Creek",
        ],
    )
    assert result.exit_code == 0
    with Database(book).open() as connection:
        save_system(
            connection,
            DitchSystem(
                ditches=(
                    Ditch(
                        code=DitchCode("L2"),
                        name="Second Lateral",
                        capacity_cfs=Decimal("12"),
                        length_feet=Decimal("10560"),
                        loss_fraction_per_mile=Decimal("0.05"),
                        turnouts=(
                            Turnout(
                                TURNOUT, "Bench gate", Decimal("5280"), Decimal("6"), Decimal("40")
                            ),
                        ),
                        diversion_mile=Decimal("28.4"),
                    ),
                )
            ),
        )
        save_register(
            connection,
            ShareRegister(
                accounts=(
                    Account(
                        AccountNumber(118), "Holder 118", date(1994, 3, 1), AccountStatus.ACTIVE
                    ),
                ),
                certificates=(
                    ShareCertificate(
                        "A-1001", AccountNumber(118), Decimal("20"), TURNOUT, date(2020, 4, 1)
                    ),
                ),
            ),
        )
        declare_season(connection, IrrigationSeason.default_for(2025), date(2025, 3, 20))
    return book


def run(book: Path, arguments: list[str]) -> tuple[int, str]:
    result = CliRunner().invoke(main, ["--book", str(book), *arguments])
    return result.exit_code, result.output


def place(book: Path, rate: str = "3") -> tuple[int, str]:
    return run(
        book,
        [
            "order",
            "place",
            "--account",
            "118",
            "--turnout",
            "L2-14",
            "--rate",
            rate,
            "--from",
            "2025-07-01T06:00",
            "--to",
            "2025-07-04T06:00",
            "--placed",
            "2025-06-28T08:00",
        ],
    )


def test_an_order_is_taken_and_numbered(district: Path) -> None:
    code, output = place(district)
    assert code == 0
    assert "order 1 taken" in output


def test_a_taken_order_is_waiting(district: Path) -> None:
    place(district)
    code, output = run(district, ["order", "list", "--waiting"])
    assert code == 0
    assert "requested" in output


def test_answering_an_order_accepts_it(district: Path) -> None:
    place(district)
    code, output = run(district, ["order", "answer", "1"])
    assert code == 0
    assert "accepted" in output
    assert "3.000 cfs" in output


def test_an_order_over_what_the_shares_entitle_is_reduced(district: Path) -> None:
    place(district, rate="9")
    code, output = run(district, ["order", "answer", "1"])
    assert code == 0
    assert "reduced" in output
    assert "shares at L2-14" in output
    assert "5.000 cfs" in output


def test_a_curtailment_holds_an_answer_down(district: Path) -> None:
    place(district)
    code, output = run(district, ["order", "answer", "1", "--curtailed-to", "1.5"])
    assert code == 0
    assert "1.500 cfs" in output
    assert "curtailment" in output


def test_an_answered_order_shows_in_the_list(district: Path) -> None:
    place(district)
    run(district, ["order", "answer", "1"])
    code, output = run(district, ["order", "list"])
    assert code == 0
    assert "accepted" in output
    assert "L2-14" in output


def test_an_order_can_be_cancelled(district: Path) -> None:
    place(district)
    code, output = run(district, ["order", "cancel", "1", "--note", "rained"])
    assert code == 0
    assert "cancelled" in output


def test_an_empty_book_lists_nothing(district: Path) -> None:
    code, output = run(district, ["order", "list"])
    assert code == 0
    assert "no orders" in output


def test_an_order_for_a_turnout_that_is_not_there_is_refused(district: Path) -> None:
    code, output = run(
        district,
        [
            "order",
            "place",
            "--account",
            "118",
            "--turnout",
            "L9-1",
            "--rate",
            "3",
            "--from",
            "2025-07-01T06:00",
            "--to",
            "2025-07-04T06:00",
            "--placed",
            "2025-06-28T08:00",
        ],
    )
    assert code != 0


def test_answering_an_order_that_is_not_there_is_refused(district: Path) -> None:
    code, output = run(district, ["order", "answer", "9"])
    assert code != 0
    assert "no order" in output


def test_a_book_that_was_never_set_up_refuses_orders(tmp_path: Path) -> None:
    code, output = run(tmp_path / "nothing.sqlite3", ["order", "list"])
    assert code != 0
    assert "never been set up" in output


def place_and_answer(district: Path, account: str, rate: str, order_id: int) -> None:
    run(
        district,
        [
            "order",
            "place",
            "--account",
            account,
            "--turnout",
            "L2-14",
            "--rate",
            rate,
            "--from",
            "2025-07-01T06:00",
            "--to",
            "2025-07-08T06:00",
            "--placed",
            "2025-06-28T08:00",
        ],
    )
    run(district, ["order", "answer", str(order_id)])


def test_a_day_with_plenty_of_water_leaves_the_orders_alone(district: Path) -> None:
    place_and_answer(district, "118", "3", 1)
    code, output = run(
        district, ["order", "allocate", "--at", "2025-07-04T12:00", "--supply", "10"]
    )
    assert code == 0
    assert "as answered" in output
    assert "3.000 of 3.000 cfs running" in output


def test_a_short_day_cuts_the_orders(district: Path) -> None:
    place_and_answer(district, "118", "3", 1)
    code, output = run(district, ["order", "allocate", "--at", "2025-07-04T12:00", "--supply", "2"])
    assert code == 0
    assert "cut under pro_rata" in output


def test_a_set_under_the_minimum_head_is_dropped(district: Path) -> None:
    place_and_answer(district, "118", "3", 1)
    code, output = run(
        district, ["order", "allocate", "--at", "2025-07-04T12:00", "--supply", "0.2"]
    )
    assert code == 0
    assert "sets dropped" in output
    assert "minimum head" in output


def test_a_day_with_nothing_running_is_refused(district: Path) -> None:
    code, output = run(
        district, ["order", "allocate", "--at", "2025-07-04T12:00", "--supply", "10"]
    )
    assert code != 0
    assert "no order was due to run" in output


def test_cutting_by_share_uses_the_stock_book(district: Path) -> None:
    place_and_answer(district, "118", "3", 1)
    code, output = run(
        district,
        ["order", "allocate", "--at", "2025-07-04T12:00", "--supply", "2", "--policy", "by-share"],
    )
    assert code == 0
    assert "cut under by_share" in output
