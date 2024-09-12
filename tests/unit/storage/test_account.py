from decimal import Decimal

import pytest

from headgate.errors import NotFoundError, PolicyError, ValidationError
from headgate.ids import AccountNumber
from headgate.storage.account import StorageBook, StorageEntry, allocate

FIRST = AccountNumber(118)
SECOND = AccountNumber(212)
THIRD = AccountNumber(300)


def shares() -> dict[AccountNumber, Decimal]:
    return {FIRST: Decimal("20"), SECOND: Decimal("20"), THIRD: Decimal("10")}


def book(usable: str = "1000") -> StorageBook:
    return allocate(2025, Decimal(usable), shares())


def test_the_pool_is_split_by_shares() -> None:
    allocated = book()
    assert allocated.balance_of(FIRST) == Decimal("400")
    assert allocated.balance_of(THIRD) == Decimal("200")


def test_the_pieces_add_back_to_the_pool() -> None:
    allocated = allocate(2025, Decimal("1000"), {FIRST: Decimal("1"), SECOND: Decimal("2")})
    assert allocated.total_allocated_af == Decimal("1000")


def test_carried_water_counts_toward_the_balance() -> None:
    allocated = allocate(2025, Decimal("1000"), shares(), {FIRST: Decimal("50")})
    assert allocated.balance_of(FIRST) == Decimal("450")


def test_an_account_with_no_shares_is_refused() -> None:
    with pytest.raises(ValidationError, match="no shares of the reservoir"):
        StorageEntry(FIRST, Decimal("0"), Decimal("100"))


def test_negative_volumes_are_refused() -> None:
    with pytest.raises(ValidationError, match="negative released volume"):
        StorageEntry(FIRST, Decimal("10"), Decimal("100"), released_af=Decimal("-1"))


def test_an_account_listed_twice_is_refused() -> None:
    entry = StorageEntry(FIRST, Decimal("10"), Decimal("100"))
    with pytest.raises(ValidationError, match="two storage entries"):
        StorageBook(water_year=2025, entries=(entry, entry))


def test_releasing_draws_the_balance_down() -> None:
    drawn = book().release_to(FIRST, Decimal("150"))
    assert drawn.balance_of(FIRST) == Decimal("250")
    assert drawn.entry_for(FIRST).released_af == Decimal("150")


def test_an_account_cannot_be_overdrawn() -> None:
    with pytest.raises(PolicyError, match="acre feet stored"):
        book().release_to(FIRST, Decimal("500"))


def test_a_negative_release_is_refused() -> None:
    with pytest.raises(ValidationError, match="may not be negative"):
        book().release_to(FIRST, Decimal("-1"))


def test_an_account_that_is_not_there_is_reported_missing() -> None:
    with pytest.raises(NotFoundError, match="no storage account"):
        book().release_to(AccountNumber(999), Decimal("1"))


def test_a_spill_comes_out_of_everybody_in_proportion() -> None:
    spilled = book().spill(Decimal("100"))
    assert spilled.balance_of(FIRST) == Decimal("360")
    assert spilled.balance_of(THIRD) == Decimal("180")
    assert spilled.total_balance_af == Decimal("900")


def test_a_spill_follows_the_balances_and_not_the_shares() -> None:
    drawn = book().release_to(FIRST, Decimal("400"))
    spilled = drawn.spill(Decimal("60"))
    assert spilled.balance_of(FIRST) == Decimal("0")
    assert spilled.balance_of(SECOND) < Decimal("400")


def test_a_spill_bigger_than_the_accounts_is_refused() -> None:
    with pytest.raises(PolicyError, match="only"):
        book().spill(Decimal("2000"))


def test_a_negative_spill_is_refused() -> None:
    with pytest.raises(ValidationError, match="may not be negative"):
        book().spill(Decimal("-1"))


def test_a_spill_from_an_empty_reservoir_changes_nothing() -> None:
    empty = allocate(2025, Decimal("0"), shares())
    assert empty.spill(Decimal("0")).total_balance_af == Decimal("0")


def test_carryover_rolls_the_balances_forward() -> None:
    carried = book().carry_over(2026)
    assert carried.water_year == 2026
    assert carried.balance_of(FIRST) == Decimal("400")
    assert carried.entry_for(FIRST).allocated_af == Decimal("0")


def test_carryover_over_the_cap_is_lost() -> None:
    carried = book().carry_over(2026, Decimal("250"))
    assert carried.balance_of(FIRST) == Decimal("250")
    assert carried.balance_of(THIRD) == Decimal("200")


def test_carrying_backwards_is_refused() -> None:
    with pytest.raises(PolicyError, match="does not come after"):
        book().carry_over(2024)


def test_a_reservoir_nobody_holds_shares_of_cannot_be_allocated() -> None:
    with pytest.raises(PolicyError, match="nobody holds shares"):
        allocate(2025, Decimal("1000"), {})


def test_a_negative_pool_cannot_be_allocated() -> None:
    with pytest.raises(ValidationError, match="negative volume"):
        allocate(2025, Decimal("-1"), shares())


def test_the_accounts_come_back_sorted() -> None:
    assert book().accounts == (FIRST, SECOND, THIRD)
