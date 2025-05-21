"""Historical consumptive use, which is the only thing a transfer may move.

A decree says four cubic feet a second. What may be moved to another farm is
not four cubic feet a second, it is what the ground actually consumed over a
study period, and the burden of showing that is on whoever wants to move it.

Three rules do the work and they compound.

A year counts only if the delivery record for it is measured. An estimated year
is a year nobody can prove, and it is left out of the average rather than
argued about. That makes a lapsed calibration in July 2019 into a smaller
transfer in 2025, which is the single most useful thing this system does.

A year counts only if it was representative. A season the right spent curtailed
is not evidence of what the farm consumes, and neither is a season the ground
sat fallow.

And in a year that does count, consumption is the smaller of what was delivered
after application losses and what the crop could physically have used. A farm
that ran water all July on twenty acres of grain does not get credit for it.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from ..errors import PolicyError, ValidationError
from ..measure.quality import Provenance
from ..model.parcel import Application, CropCode
from ..units import round_volume
from .requirement import net_acre_feet

DEFAULT_STUDY_YEARS = 10
MINIMUM_COUNTED_YEARS = 5
CURTAILMENT_LIMIT_DAYS = 30


@dataclass(frozen=True, slots=True)
class SeasonRecord:
    """One year of a farm's history, as the delivery record has it."""

    water_year: int
    delivered_af: Decimal
    provenance: Provenance
    irrigated_acres: Decimal
    crop: CropCode
    application: Application
    curtailed_days: int = 0

    def __post_init__(self) -> None:
        if self.delivered_af < 0:
            raise ValidationError(f"{self.water_year} shows a negative delivery")
        if self.irrigated_acres < 0:
            raise ValidationError(f"{self.water_year} shows negative acres")
        if self.curtailed_days < 0:
            raise ValidationError(f"{self.water_year} shows a negative curtailment")

    @property
    def crop_requirement_af(self) -> Decimal:
        return net_acre_feet(self.crop, self.irrigated_acres)

    @property
    def consumed_af(self) -> Decimal:
        """The smaller of what the ground could use and what it was given."""

        applied = round_volume(self.delivered_af * self.application.efficiency)
        requirement = self.crop_requirement_af
        return applied if applied < requirement else requirement


@dataclass(frozen=True, slots=True)
class YearFinding:
    """What the study made of one year."""

    water_year: int
    consumed_af: Decimal
    counted: bool
    reason: str


@dataclass(frozen=True, slots=True)
class HistoricalUse:
    """The study, its findings, and the number that comes out of it."""

    findings: tuple[YearFinding, ...]
    average_af: Decimal

    @property
    def counted(self) -> tuple[YearFinding, ...]:
        return tuple(item for item in self.findings if item.counted)

    @property
    def excluded(self) -> tuple[YearFinding, ...]:
        return tuple(item for item in self.findings if not item.counted)

    @property
    def counted_years(self) -> int:
        return len(self.counted)

    @property
    def study_years(self) -> int:
        return len(self.findings)

    def finding_for(self, water_year: int) -> YearFinding:
        for item in self.findings:
            if item.water_year == water_year:
                return item
        raise PolicyError(f"{water_year} was not in the study period")


def _judge(record: SeasonRecord, curtailment_limit_days: int, count_curtailed: bool) -> YearFinding:
    consumed = record.consumed_af
    if not record.provenance.counts_as_evidence:
        return YearFinding(
            record.water_year,
            consumed,
            False,
            f"the {record.water_year} record is {record.provenance.value}",
        )
    if record.crop is CropCode.FALLOW:
        return YearFinding(
            record.water_year, consumed, False, f"the ground was fallow in {record.water_year}"
        )
    if record.curtailed_days > curtailment_limit_days and not count_curtailed:
        return YearFinding(
            record.water_year,
            consumed,
            False,
            f"the right was curtailed {record.curtailed_days} days in {record.water_year}",
        )
    return YearFinding(record.water_year, consumed, True, "measured and representative")


def analyse(
    records: list[SeasonRecord],
    minimum_years: int = MINIMUM_COUNTED_YEARS,
    curtailment_limit_days: int = CURTAILMENT_LIMIT_DAYS,
    count_curtailed: bool = False,
) -> HistoricalUse:
    """Work a study period down to one number, or refuse to."""

    if not records:
        raise PolicyError("a consumptive use study needs a delivery record")
    years = [record.water_year for record in records]
    if len(set(years)) != len(years):
        raise ValidationError("the study period lists a year twice")
    findings = tuple(
        _judge(record, curtailment_limit_days, count_curtailed)
        for record in sorted(records, key=lambda item: item.water_year)
    )
    counted = [item for item in findings if item.counted]
    if len(counted) < minimum_years:
        raise PolicyError(
            f"{len(counted)} years of the study are usable and the rule asks for {minimum_years}"
        )
    total = sum((item.consumed_af for item in counted), Decimal("0"))
    return HistoricalUse(findings=findings, average_af=round_volume(total / Decimal(len(counted))))


def transferable_af(study: HistoricalUse, fraction: Decimal = Decimal("1")) -> Decimal:
    """The part of the historical use an applicant is asking to move."""

    if fraction <= 0 or fraction > 1:
        raise ValidationError(f"{fraction} is not a share of a historical use")
    return round_volume(study.average_af * fraction)


def return_flow_af(delivered_af: Decimal, consumed_af: Decimal) -> Decimal:
    """What went back to the stream, which the transfer may not take."""

    if consumed_af > delivered_af:
        raise PolicyError("a farm cannot consume more than it was delivered")
    return round_volume(delivered_af - consumed_af)
