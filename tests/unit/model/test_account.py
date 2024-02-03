from datetime import date
from decimal import Decimal

import pytest

from headgate.errors import ConflictError, NotFoundError, PolicyError, ValidationError
from headgate.ids import AccountNumber, TurnoutCode
from headgate.model.account import (
    Account,
    AccountStatus,
    ShareCertificate,
    ShareRegister,
)


def account(number: int, status: AccountStatus = AccountStatus.ACTIVE) -> Account:
    return Account(
        number=AccountNumber(number),
        name=f"Holder {number}",
        joined=date(1994, 3, 1),
        status=status,
    )


def certificate(
    serial: str, number: int, shares: str, turnout: str = "L2-14", issued: date = date(2020, 4, 1)
) -> ShareCertificate:
    return ShareCertificate(
        serial=serial,
        account=AccountNumber(number),
        shares=Decimal(shares),
        turnout=TurnoutCode(turnout),
        issued=issued,
    )


def register() -> ShareRegister:
    return ShareRegister(
        accounts=(account(118), account(212), account(300, AccountStatus.CLOSED)),
        certificates=(
            certificate("A-1001", 118, "12"),
            certificate("A-1002", 212, "4", "L2-20"),
            certificate("A-1003", 118, "6", "L2-20", date(2023, 5, 1)),
        ),
    )


def test_an_account_needs_a_name() -> None:
    with pytest.raises(ValidationError, match="no name on it"):
        Account(number=AccountNumber(1), name="   ", joined=date(2020, 1, 1))


def test_only_an_active_account_takes_delivery() -> None:
    assert account(118).takes_delivery
    assert not account(118, AccountStatus.SUSPENDED).takes_delivery


def test_a_certificate_serial_has_a_shape() -> None:
    with pytest.raises(ValidationError, match="not a certificate serial"):
        certificate("1001", 118, "12")


def test_a_certificate_carries_shares() -> None:
    with pytest.raises(ValidationError, match="carries no shares"):
        certificate("A-1", 118, "0")


def test_a_certificate_cannot_be_retired_before_it_was_issued() -> None:
    with pytest.raises(ValidationError, match="before it was issued"):
        ShareCertificate(
            serial="A-1",
            account=AccountNumber(118),
            shares=Decimal("1"),
            turnout=TurnoutCode("L2-14"),
            issued=date(2021, 4, 1),
            retired=date(2020, 4, 1),
        )


def test_a_certificate_is_outstanding_from_the_day_it_was_issued() -> None:
    item = certificate("A-1", 118, "3", issued=date(2021, 4, 1))
    assert not item.held_on(date(2021, 3, 31))
    assert item.held_on(date(2021, 4, 1))


def test_the_register_refuses_a_certificate_held_by_a_stranger() -> None:
    with pytest.raises(ValidationError, match="not in the register"):
        ShareRegister(accounts=(account(118),), certificates=(certificate("A-1", 999, "1"),))


def test_the_register_refuses_a_repeated_serial() -> None:
    with pytest.raises(ValidationError, match="appears twice"):
        ShareRegister(
            accounts=(account(118),),
            certificates=(certificate("A-1", 118, "1"), certificate("A-1", 118, "2")),
        )


def test_the_register_refuses_a_repeated_account() -> None:
    with pytest.raises(ValidationError, match="appears twice"):
        ShareRegister(accounts=(account(118), account(118)))


def test_shares_are_counted_as_of_a_day() -> None:
    book = register()
    assert book.shares_of(AccountNumber(118), date(2022, 6, 1)) == Decimal("12")
    assert book.shares_of(AccountNumber(118), date(2024, 6, 1)) == Decimal("18")


def test_shares_are_counted_by_turnout_and_in_total() -> None:
    book = register()
    assert book.shares_at(TurnoutCode("L2-20"), date(2024, 6, 1)) == Decimal("10")
    assert book.total_shares(date(2024, 6, 1)) == Decimal("22")


def test_an_unknown_account_or_certificate_is_reported_missing() -> None:
    with pytest.raises(NotFoundError, match="no account"):
        register().account(AccountNumber(999))
    with pytest.raises(NotFoundError, match="no certificate"):
        register().certificate("A-9999")


def test_issuing_adds_to_the_book() -> None:
    book = register().issue(certificate("A-1004", 212, "2"))
    assert book.total_shares(date(2024, 6, 1)) == Decimal("24")


def test_a_closed_account_cannot_be_issued_shares() -> None:
    with pytest.raises(PolicyError, match="closed and cannot be issued"):
        register().issue(certificate("A-1004", 300, "2"))


def test_a_serial_cannot_be_reused() -> None:
    with pytest.raises(ConflictError, match="already in the book"):
        register().issue(certificate("A-1001", 212, "2"))


def test_a_transfer_retires_the_old_certificate_and_writes_a_new_one() -> None:
    book = register().transfer("A-1001", AccountNumber(212), date(2024, 7, 1), "A-2001")
    assert book.shares_of(AccountNumber(118), date(2024, 8, 1)) == Decimal("6")
    assert book.shares_of(AccountNumber(212), date(2024, 8, 1)) == Decimal("16")
    assert book.shares_of(AccountNumber(118), date(2024, 6, 1)) == Decimal("18")


def test_a_transfer_keeps_the_water_at_the_same_turnout() -> None:
    book = register().transfer("A-1001", AccountNumber(212), date(2024, 7, 1), "A-2001")
    assert book.certificate("A-2001").turnout == TurnoutCode("L2-14")


def test_a_certificate_already_retired_cannot_be_transferred() -> None:
    book = register().transfer("A-1001", AccountNumber(212), date(2024, 7, 1), "A-2001")
    with pytest.raises(PolicyError, match="not outstanding"):
        book.transfer("A-1001", AccountNumber(118), date(2024, 8, 1), "A-2002")


def test_a_transfer_to_a_closed_account_is_refused() -> None:
    with pytest.raises(PolicyError, match="closed and cannot take"):
        register().transfer("A-1001", AccountNumber(300), date(2024, 7, 1), "A-2001")
