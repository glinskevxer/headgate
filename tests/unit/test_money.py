from decimal import Decimal

import pytest

from headgate.errors import ValidationError
from headgate.money import Money


def test_money_reads_and_prints_in_dollars() -> None:
    assert Money.from_dollars("1234.56").cents == 123456
    assert str(Money.from_dollars("1234.56")) == "$1,234.56"
    assert Money.from_dollars("1234.56").dollars == Decimal("1234.56")


def test_a_credit_prints_with_its_sign() -> None:
    assert str(Money(-2550)) == "-$25.50"


def test_money_parses_what_a_clerk_types() -> None:
    assert Money.parse(" $1,234.56 ") == Money(123456)


def test_an_empty_amount_is_refused() -> None:
    with pytest.raises(ValidationError, match="empty string"):
        Money.parse("   ")


def test_a_word_is_not_an_amount() -> None:
    with pytest.raises(ValidationError, match="not an amount"):
        Money.parse("twelve dollars")


def test_half_a_cent_rounds_up() -> None:
    assert Money.from_dollars("0.005") == Money(1)


def test_money_adds_subtracts_and_negates() -> None:
    assert Money(500) + Money(250) == Money(750)
    assert Money(500) - Money(750) == Money(-250)
    assert -Money(500) == Money(-500)


def test_multiplying_rounds_to_the_cent() -> None:
    assert Money(1000).times(Decimal("0.0725")) == Money(73)


def test_an_allocation_adds_back_to_the_whole() -> None:
    pieces = Money(10000).allocate([Decimal("1"), Decimal("1"), Decimal("1")])
    assert sum(piece.cents for piece in pieces) == 10000
    assert [piece.cents for piece in pieces] == [3334, 3333, 3333]


def test_an_allocation_follows_the_weights() -> None:
    pieces = Money(10000).allocate([Decimal("3"), Decimal("1")])
    assert [piece.cents for piece in pieces] == [7500, 2500]


def test_a_credit_allocates_without_losing_a_cent() -> None:
    pieces = Money(-10000).allocate([Decimal("1"), Decimal("1"), Decimal("1")])
    assert sum(piece.cents for piece in pieces) == -10000


def test_a_zero_weight_gets_nothing() -> None:
    pieces = Money(999).allocate([Decimal("0"), Decimal("1")])
    assert pieces[0] == Money.zero()
    assert pieces[1] == Money(999)


def test_allocating_across_nothing_is_refused() -> None:
    with pytest.raises(ValidationError, match="nothing to allocate"):
        Money(100).allocate([])


def test_a_negative_weight_is_refused() -> None:
    with pytest.raises(ValidationError, match="may not be negative"):
        Money(100).allocate([Decimal("-1"), Decimal("2")])


def test_weights_that_are_all_zero_are_refused() -> None:
    with pytest.raises(ValidationError, match="positive weight"):
        Money(100).allocate([Decimal("0"), Decimal("0")])
