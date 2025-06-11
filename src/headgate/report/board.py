"""The packet the board gets before the November meeting.

Five pages, in the order they get argued about: what the creek brought, what
the ditch delivered, what it lost, what it billed, and what is wrong that
nobody has fixed. Everything in it comes from a report that already exists;
this is the cover sheet that puts them in one order and says which numbers the
board is being asked to accept.

The last section is the one that matters. A packet with nothing in it reads as
a good year. A packet listing four turnouts nobody measured is the board being
told, in writing, before it adopts a rate for next season.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from ..assessment.billing import BillRun
from ..errors import PolicyError
from ..money import Money
from ..report.exceptions import ExceptionReport
from ..report.season import SeasonReport


@dataclass(frozen=True, slots=True)
class BoardPacket:
    """One season, as the board is asked to accept it."""

    season: SeasonReport
    bills: BillRun
    exceptions: ExceptionReport
    proved_floor: Decimal = Decimal("0.9")

    @property
    def water_year(self) -> int:
        return self.season.water_year

    @property
    def billed(self) -> Money:
        return self.bills.total

    @property
    def accounts_billed(self) -> int:
        return len(self.bills.bills)

    @property
    def is_proved(self) -> bool:
        return self.season.proved_share >= self.proved_floor

    @property
    def wants_attention(self) -> int:
        return len(self.exceptions.exceptions)

    @property
    def can_be_adopted(self) -> bool:
        """Whether the board is being asked to accept a season worth accepting."""

        return self.is_proved and not self.exceptions.costing_water

    def reasons_not_to_adopt(self) -> tuple[str, ...]:
        found: list[str] = []
        if not self.is_proved:
            found.append(
                f"only {self.season.proved_share} of the season is proved, against a floor "
                f"of {self.proved_floor}"
            )
        for item in self.exceptions.costing_water:
            found.append(f"{item.subject}: {item.detail}")
        return tuple(found)

    def summary(self) -> list[tuple[str, str]]:
        return [
            ("district", self.season.district),
            ("water year", str(self.water_year)),
            ("headgate", f"{self.season.headgate_af:.2f} acre feet"),
            ("delivered", f"{self.season.delivered_af:.2f} acre feet"),
            ("ditch loss", f"{self.season.loss_af:.2f} acre feet"),
            ("unexplained", f"{self.season.unexplained_loss_af:.2f} acre feet"),
            ("carriage", f"{self.season.carriage_efficiency}"),
            ("proved", f"{self.season.proved_share}"),
            ("billed", str(self.billed)),
            ("accounts", str(self.accounts_billed)),
            ("wants attention", str(self.wants_attention)),
            ("recommend adopting", "yes" if self.can_be_adopted else "no"),
        ]

    def sections(self) -> list[tuple[str, list[list[str]]]]:
        """The packet's tables, in the order they are read out."""

        return [
            ("deliveries", self.season.rows()),
            (
                "assessment",
                [
                    [str(bill.account), str(bill.total), str(len(bill.lines))]
                    for bill in self.bills.bills
                ],
            ),
            ("exceptions", self.exceptions.rows()),
        ]


def build(
    season: SeasonReport,
    bills: BillRun,
    exceptions: ExceptionReport,
    proved_floor: Decimal = Decimal("0.9"),
) -> BoardPacket:
    """Put the packet together, refusing to mix two seasons in one."""

    if bills.water_year != season.water_year:
        raise PolicyError(
            f"the {bills.water_year} bills do not belong in the {season.water_year} packet"
        )
    if proved_floor < 0 or proved_floor > 1:
        raise PolicyError(f"{proved_floor} is not a share of a season")
    return BoardPacket(season=season, bills=bills, exceptions=exceptions, proved_floor=proved_floor)
