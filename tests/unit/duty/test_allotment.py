from datetime import date
from decimal import Decimal

import pytest

from headgate.duty.allotment import Allotment, AllotmentLedger, AllotmentUse, allot
from headgate.errors import NotFoundError, PolicyError, ValidationError
from headgate.ids import AccountNumber

FIRST = AccountNumber(118)
SECOND = AccountNumber(212)
SET_ON = date(2025, 4, 1)


def shares() -> dict[AccountNumber, Decimal]:
    return {FIRST: Decimal("20"), SECOND: Decimal("10")}


def ledger(available: str = "600", cap: str | None = None) -> AllotmentLedger:
    return allot(
        2025,
        Decimal(available),
        shares(),
        SET_ON,
        "April forecast",
        Decimal(cap) if cap is not None else None,
    )


def test_the_supply_is_divided_by_the_shares() -> None:
    assert ledger().allotment.af_per_share == Decimal("20")
    assert ledger().allowed_af(FIRST) == Decimal("400")


def test_the_duty_caps_a_generous_year() -> None:
    assert ledger("3000", cap="40").allotment.af_per_share == Decimal("40")


def test_a_year_under_the_cap_is_left_alone() -> None:
    assert ledger("600", cap="40").allotment.af_per_share == Decimal("20")


def test_a_district_with_no_shares_cannot_allot() -> None:
    with pytest.raises(PolicyError, match="nothing to allot"):
        allot(2025, Decimal("600"), {}, SET_ON, "April forecast")


def test_a_negative_supply_is_refused() -> None:
    with pytest.raises(ValidationError, match="negative supply"):
        allot(2025, Decimal("-1"), shares(), SET_ON, "April forecast")


def test_an_allotment_says_what_it_came_from() -> None:
    with pytest.raises(ValidationError, match="what it was worked out from"):
        Allotment(2025, Decimal("20"), SET_ON, "   ")


def test_a_negative_allotment_is_refused() -> None:
    with pytest.raises(ValidationError, match="less than nothing"):
        Allotment(2025, Decimal("-1"), SET_ON, "April forecast")


def test_taking_water_draws_the_allotment_down() -> None:
    used = ledger().take(FIRST, Decimal("150"))
    assert used.remaining_af(FIRST) == Decimal("250")
    assert not used.is_over(FIRST)


def test_an_account_cannot_take_more_than_it_has_left() -> None:
    with pytest.raises(PolicyError, match="allotment left"):
        ledger().take(FIRST, Decimal("500"))


def test_a_negative_delivery_is_refused() -> None:
    with pytest.raises(ValidationError, match="may not be negative"):
        ledger().take(FIRST, Decimal("-1"))


def test_an_account_that_is_not_on_the_ledger_is_reported_missing() -> None:
    with pytest.raises(NotFoundError, match="no allotment account"):
        ledger().take(AccountNumber(999), Decimal("1"))


def test_the_allotment_can_be_raised_early_in_the_season() -> None:
    raised = ledger().allotment.revise(Decimal("28"), date(2025, 6, 1), "May runoff came in")
    assert raised.af_per_share == Decimal("28")
    assert raised.revision == 1


def test_the_allotment_may_not_be_raised_late() -> None:
    with pytest.raises(PolicyError, match="may not be raised after"):
        ledger().allotment.revise(Decimal("28"), date(2025, 8, 1), "late storm")


def test_the_allotment_may_be_cut_at_any_time() -> None:
    cut = ledger().allotment.revise(Decimal("12"), date(2025, 8, 1), "creek quit")
    assert cut.af_per_share == Decimal("12")


def test_an_allotment_cannot_be_revised_backwards_in_time() -> None:
    with pytest.raises(PolicyError, match="cannot be revised on"):
        ledger().allotment.revise(Decimal("12"), date(2025, 3, 1), "too early")


def test_a_cut_never_claws_back_water_already_delivered() -> None:
    used = ledger().take(FIRST, Decimal("380"))
    cut = used.under(used.allotment.revise(Decimal("12"), date(2025, 8, 1), "creek quit"))
    assert cut.remaining_af(FIRST) == Decimal("0")
    assert cut.is_over(FIRST)
    assert cut.over_by(FIRST) == Decimal("140")


def test_the_overdrawn_accounts_are_listed() -> None:
    used = ledger().take(FIRST, Decimal("380"))
    cut = used.under(used.allotment.revise(Decimal("12"), date(2025, 8, 1), "creek quit"))
    assert [item.account for item in cut.overdrawn] == [FIRST]


def test_an_allotment_from_another_year_cannot_be_applied() -> None:
    other = Allotment(2024, Decimal("20"), date(2024, 4, 1), "April forecast")
    with pytest.raises(PolicyError, match="cannot be applied"):
        ledger().under(other)


def test_an_open_year_sets_no_allotment_at_all() -> None:
    assert Allotment(2025, Decimal("0"), SET_ON, "no rationing").is_open
    assert not ledger().allotment.is_open


def test_an_account_listed_twice_is_refused() -> None:
    use = AllotmentUse(FIRST, Decimal("20"), Decimal("0"))
    with pytest.raises(ValidationError, match="on the ledger twice"):
        AllotmentLedger(allotment=ledger().allotment, uses=(use, use))


def test_a_negative_use_is_refused() -> None:
    with pytest.raises(ValidationError, match="negative volume"):
        AllotmentUse(FIRST, Decimal("20"), Decimal("-1"))
