"""Closing a season.

Everything the district did between April and October comes together here, in
one order that does not vary. The delivery ledger is totalled. The difference
between the headgate and the turnouts is the loss, and it is charged out under
whatever rule the board adopted. Each account's water and its share of the loss
are billed. The report is built from the same ledger the bills came off, so the
two cannot disagree.

The one thing this refuses to do is close a season it cannot account for. A
turnout that ran and has no owner behind it, or a season where the turnouts
took more than the headgate passed, is a bookkeeping problem and it gets fixed
before the bills go out, not after.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from ..assessment.billing import Bill, BillRun, bill_account
from ..assessment.tiers import RateSchedule
from ..carriage.apportion import Apportionment, LossPolicy, apportion, measured_loss
from ..errors import PolicyError
from ..ids import AccountNumber, TurnoutCode
from ..measure.delivery import DeliveryLedger
from ..model.ditch import DitchSystem
from ..money import Money
from ..report.season import SeasonReport, build
from ..units import round_volume


@dataclass(frozen=True, slots=True)
class AccountSeason:
    """What one account took and what it is being charged for."""

    account: AccountNumber
    shares: Decimal
    delivered_af: Decimal
    loss_af: Decimal

    @property
    def charged_af(self) -> Decimal:
        return round_volume(self.delivered_af + self.loss_af)


@dataclass(frozen=True, slots=True)
class SeasonClose:
    """Everything that comes out of closing a season."""

    water_year: int
    report: SeasonReport
    apportionment: Apportionment
    accounts: tuple[AccountSeason, ...]
    bills: BillRun

    @property
    def billed(self) -> Money:
        return self.bills.total

    @property
    def delivered_af(self) -> Decimal:
        return self.report.delivered_af

    @property
    def loss_af(self) -> Decimal:
        return self.report.loss_af

    def account_season(self, account: AccountNumber) -> AccountSeason:
        for item in self.accounts:
            if item.account == account:
                return item
        raise PolicyError(f"account {account} took no water in {self.water_year}")

    def bill_for(self, account: AccountNumber) -> Bill:
        return self.bills.bill_for(account)


def _gather(
    ledger: DeliveryLedger,
    apportionment: Apportionment,
    turnout_accounts: Mapping[TurnoutCode, AccountNumber],
    shares: Mapping[AccountNumber, Decimal],
) -> tuple[AccountSeason, ...]:
    delivered: dict[AccountNumber, Decimal] = {}
    lost: dict[AccountNumber, Decimal] = {}
    for record in ledger.records:
        owner = turnout_accounts.get(record.turnout)
        if owner is None:
            raise PolicyError(f"turnout {record.turnout} ran and no account stands behind it")
        delivered[owner] = delivered.get(owner, Decimal("0")) + record.total_af
        lost[owner] = (
            lost.get(owner, Decimal("0")) + apportionment.for_turnout(record.turnout).loss_af
        )
    for account in shares:
        delivered.setdefault(account, Decimal("0"))
        lost.setdefault(account, Decimal("0"))
    return tuple(
        AccountSeason(
            account=account,
            shares=shares.get(account, Decimal("0")),
            delivered_af=round_volume(delivered[account]),
            loss_af=round_volume(lost[account]),
        )
        for account in sorted(delivered)
    )


def close_season(
    water_year: int,
    district: str,
    ledger: DeliveryLedger,
    headgate_af: Decimal,
    system: DitchSystem,
    schedule: RateSchedule,
    turnout_accounts: Mapping[TurnoutCode, AccountNumber],
    shares: Mapping[AccountNumber, Decimal],
    issued_on: date,
    policy: LossPolicy = LossPolicy.BY_LEG,
    turnout_shares: Mapping[TurnoutCode, Decimal] | None = None,
) -> SeasonClose:
    """Total the season, charge the loss out, and build the bills."""

    volumes = ledger.volumes()
    if not volumes:
        raise PolicyError(f"no turnout ran in {water_year}, so there is nothing to close")
    loss = measured_loss(headgate_af, volumes)
    split = apportion(volumes, loss, policy, system=system, shares=turnout_shares)
    report = build(water_year, district, ledger, split, headgate_af, system)
    accounts = _gather(ledger, split, turnout_accounts, shares)
    bills = BillRun(
        water_year=water_year,
        issued_on=issued_on,
        bills=tuple(
            bill_account(
                account=item.account,
                water_year=water_year,
                issued_on=issued_on,
                schedule=schedule,
                shares=item.shares,
                delivered_af=item.delivered_af,
                loss_af=item.loss_af,
            )
            for item in accounts
        ),
    )
    return SeasonClose(
        water_year=water_year,
        report=report,
        apportionment=split,
        accounts=accounts,
        bills=bills,
    )
