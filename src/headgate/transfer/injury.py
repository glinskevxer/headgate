"""The no injury rule, which is what actually decides a transfer.

Nobody else's water may get worse. That sounds like one test and it is three,
because a right can be hurt in three different ways and an applicant will find
whichever one nobody checked.

By quantity, when the ground the water is moving to consumes more in some month
than the ground it came off did. The season total can be identical and the
transfer still take July water away from somebody.

By reach, when the headgate moves upstream past somebody. Every right that used
to divert between the old point and the new one now has that water taken out
above it rather than below, and it does not matter that the total is the same.

By return flow, when the old farm's waste used to come back to the stream at a
place and a time other rights had come to rely on. Moving the farm moves the
waste, and the applicant owes the difference.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal

from ..duty.requirement import SEASON_MONTHS, net_inches
from ..errors import PolicyError, ValidationError
from ..ids import DecreeNumber
from ..model.parcel import CropCode
from ..model.right import WaterRight
from ..units import round_volume

DEFAULT_TOLERANCE_AF = Decimal("0.5")


def monthly_pattern(consumed_af: Decimal, crop: CropCode) -> dict[int, Decimal]:
    """Spread a season's consumption over the months the crop uses it."""

    if consumed_af < 0:
        raise ValidationError("a consumption pattern may not start from a negative volume")
    weights = {month: net_inches(crop, month) for month in SEASON_MONTHS}
    total = sum(weights.values(), Decimal("0"))
    if total <= 0:
        raise PolicyError(f"{crop.value} uses no water in any month, so it has no pattern")
    pattern = {month: round_volume(consumed_af * weights[month] / total) for month in SEASON_MONTHS}
    residue = round_volume(consumed_af - sum(pattern.values(), Decimal("0")))
    if residue != 0:
        peak = max(SEASON_MONTHS, key=lambda month: (pattern[month], month))
        pattern[peak] = round_volume(pattern[peak] + residue)
    return pattern


@dataclass(frozen=True, slots=True)
class MonthFinding:
    """One month, before and after."""

    month: int
    before_af: Decimal
    after_af: Decimal

    @property
    def change_af(self) -> Decimal:
        return round_volume(self.after_af - self.before_af)


@dataclass(frozen=True, slots=True)
class InjuryReview:
    """What the review found, and whether it is fatal."""

    months: tuple[MonthFinding, ...]
    rights_in_the_reach: tuple[DecreeNumber, ...]
    tolerance_af: Decimal
    return_flow_shortfall_af: Decimal

    @property
    def worst_month(self) -> MonthFinding | None:
        if not self.months:
            return None
        return max(self.months, key=lambda item: item.change_af)

    @property
    def injures_by_quantity(self) -> bool:
        return any(item.change_af > self.tolerance_af for item in self.months)

    @property
    def injures_by_reach(self) -> bool:
        return bool(self.rights_in_the_reach)

    @property
    def injures_by_return_flow(self) -> bool:
        return self.return_flow_shortfall_af > self.tolerance_af

    @property
    def injures(self) -> bool:
        return self.injures_by_quantity or self.injures_by_reach or self.injures_by_return_flow

    @property
    def reasons(self) -> tuple[str, ...]:
        found: list[str] = []
        if self.injures_by_quantity:
            worst = self.worst_month
            assert worst is not None
            found.append(
                f"month {worst.month} takes {worst.change_af} acre feet more than it used to"
            )
        if self.injures_by_reach:
            names = ", ".join(str(decree) for decree in self.rights_in_the_reach)
            found.append(f"the headgate moves above {names}")
        if self.injures_by_return_flow:
            found.append(
                f"{self.return_flow_shortfall_af} acre feet of return flow would stop coming back"
            )
        return tuple(found)


def rights_in_reach(
    rights: list[WaterRight], from_mile: Decimal, to_mile: Decimal
) -> tuple[DecreeNumber, ...]:
    """Every right that diverts between an old headgate and a new one."""

    if to_mile <= from_mile:
        return ()
    return tuple(
        right.decree
        for right in rights
        if right.is_active and from_mile < right.diversion_mile <= to_mile
    )


def review(
    before: Mapping[int, Decimal],
    after: Mapping[int, Decimal],
    rights: list[WaterRight] | None = None,
    from_mile: Decimal | None = None,
    to_mile: Decimal | None = None,
    return_flow_owed_af: Decimal = Decimal("0"),
    return_flow_replaced_af: Decimal = Decimal("0"),
    tolerance_af: Decimal = DEFAULT_TOLERANCE_AF,
) -> InjuryReview:
    """Run all three tests and report every one that fails."""

    if tolerance_af < 0:
        raise ValidationError("a tolerance may not be negative")
    months = tuple(
        MonthFinding(
            month=month,
            before_af=before.get(month, Decimal("0")),
            after_af=after.get(month, Decimal("0")),
        )
        for month in sorted(set(before) | set(after))
    )
    in_reach: tuple[DecreeNumber, ...] = ()
    if rights is not None and from_mile is not None and to_mile is not None:
        in_reach = rights_in_reach(rights, from_mile, to_mile)
    shortfall = round_volume(return_flow_owed_af - return_flow_replaced_af)
    return InjuryReview(
        months=months,
        rights_in_the_reach=in_reach,
        tolerance_af=tolerance_af,
        return_flow_shortfall_af=shortfall if shortfall > 0 else Decimal("0"),
    )


def require_no_injury(found: InjuryReview) -> InjuryReview:
    """Insist a review came back clean, for a caller about to approve."""

    if found.injures:
        raise PolicyError("the transfer would injure other rights: " + "; ".join(found.reasons))
    return found
