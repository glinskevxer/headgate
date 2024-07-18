from datetime import date
from decimal import Decimal

import pytest

from headgate.assessment.billing import Bill, ChargeKind, bill_account
from headgate.assessment.repost import Restatement, restate, reverse, volume_moved
from headgate.assessment.tiers import Band, RateSchedule
from headgate.errors import PolicyError, ValidationError
from headgate.ids import AccountNumber
from headgate.money import Money

ISSUED = date(2025, 11, 1)
REPOSTED = date(2026, 1, 15)


def schedule() -> RateSchedule:
    return RateSchedule(
        water_year=2025,
        per_share=Money.from_dollars("4.50"),
        bands=(
            Band(Decimal("50"), Money.from_dollars("2.00")),
            Band(Decimal("150"), Money.from_dollars("3.50")),
            Band(None, Money.from_dollars("6.00")),
        ),
    )


def bill(delivered: str = "160", account: int = 118, **extra: object) -> Bill:
    fields: dict[str, object] = {
        "account": AccountNumber(account),
        "water_year": 2025,
        "issued_on": ISSUED,
        "schedule": schedule(),
        "shares": Decimal("20"),
        "delivered_af": Decimal(delivered),
    }
    fields.update(extra)
    return bill_account(**fields)  # type: ignore[arg-type]


def test_a_reversal_cancels_the_bill_it_reverses() -> None:
    original = bill()
    reversed_bill = reverse(original, REPOSTED, "weir read high all season")
    assert (original.total + reversed_bill.total) == Money.zero()


def test_a_reversal_says_which_line_it_reverses() -> None:
    reversed_bill = reverse(bill(), REPOSTED, "weir read high all season")
    assert all("reversal:" in line.description for line in reversed_bill.lines)


def test_a_reversal_of_a_credit_becomes_a_charge_again() -> None:
    original = bill(credit=Money.from_dollars("40.00"))
    reversed_bill = reverse(original, REPOSTED, "weir read high all season")
    kinds = {line.kind for line in reversed_bill.lines}
    assert ChargeKind.PENALTY in kinds
    assert (original.total + reversed_bill.total) == Money.zero()


def test_a_reversal_needs_a_reason() -> None:
    with pytest.raises(ValidationError, match="says why"):
        reverse(bill(), REPOSTED, "  ")


def test_a_restatement_reports_the_adjustment() -> None:
    corrected = bill(delivered="140")
    found = restate(bill(), corrected, "weir read high all season", REPOSTED)
    assert found.is_a_credit
    assert found.adjustment.cents < 0


def test_a_lower_delivery_can_drop_a_band_and_the_credit_shows_it() -> None:
    original = bill(delivered="160")
    corrected = bill(delivered="40")
    found = restate(original, corrected, "weir read high all season", REPOSTED, board_approved=True)
    assert found.adjustment.cents < -25000


def test_the_net_owed_is_the_reversal_plus_the_replacement() -> None:
    corrected = bill(delivered="140")
    found = restate(bill(), corrected, "weir read high all season", REPOSTED)
    assert found.net_owed == corrected.total - bill().total


def test_a_small_restatement_does_not_need_the_board() -> None:
    corrected = bill(delivered="155")
    found = restate(bill(), corrected, "weir read high all season", REPOSTED)
    assert not found.needs_board_approval


def test_a_large_restatement_needs_the_board() -> None:
    corrected = bill(delivered="40")
    with pytest.raises(PolicyError, match="needs the board"):
        restate(bill(), corrected, "weir read high all season", REPOSTED)


def test_the_board_can_approve_a_large_restatement() -> None:
    corrected = bill(delivered="40")
    found = restate(bill(), corrected, "weir read high", REPOSTED, board_approved=True)
    assert found.needs_board_approval


def test_a_restatement_may_not_move_a_bill_to_another_account() -> None:
    with pytest.raises(PolicyError, match="another account"):
        Restatement(
            original=bill(),
            reversal=reverse(bill(), REPOSTED, "weir"),
            replacement=bill(account=212),
            reason="weir",
            reposted_on=REPOSTED,
        )


def test_a_restatement_may_not_move_a_bill_to_another_season() -> None:
    other = bill_account(
        account=AccountNumber(118),
        water_year=2024,
        issued_on=ISSUED,
        schedule=RateSchedule(
            2024, Money.from_dollars("4.50"), (Band(None, Money.from_dollars("2.00")),)
        ),
        shares=Decimal("20"),
        delivered_af=Decimal("100"),
    )
    with pytest.raises(PolicyError, match="another season"):
        Restatement(
            original=bill(),
            reversal=reverse(bill(), REPOSTED, "weir"),
            replacement=other,
            reason="weir",
            reposted_on=REPOSTED,
        )


def test_a_restatement_needs_a_reason() -> None:
    with pytest.raises(ValidationError, match="says why"):
        restate(bill(), bill(delivered="150"), "   ", REPOSTED)


def test_a_restatement_describes_itself_for_the_minutes() -> None:
    found = restate(bill(), bill(delivered="150"), "weir read high", REPOSTED)
    text = found.describe()
    assert "restated on 2026-01-15" in text
    assert "credit" in text


def test_the_volume_that_moved_is_reported_on_its_own() -> None:
    assert volume_moved(Decimal("160"), Decimal("142.5")) == Decimal("-17.5000")
