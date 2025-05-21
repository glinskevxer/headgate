from decimal import Decimal

import pytest

from headgate.duty.hcu import (
    HistoricalUse,
    SeasonRecord,
    analyse,
    return_flow_af,
    transferable_af,
)
from headgate.errors import PolicyError, ValidationError
from headgate.measure.quality import Provenance
from headgate.model.parcel import Application, CropCode


def record(
    year: int,
    delivered: str = "160",
    provenance: Provenance = Provenance.MEASURED,
    acres: str = "40",
    crop: CropCode = CropCode.ALFALFA,
    curtailed: int = 0,
) -> SeasonRecord:
    return SeasonRecord(
        water_year=year,
        delivered_af=Decimal(delivered),
        provenance=provenance,
        irrigated_acres=Decimal(acres),
        crop=crop,
        application=Application.FLOOD,
        curtailed_days=curtailed,
    )


def ten_years() -> list[SeasonRecord]:
    return [record(year) for year in range(2015, 2025)]


def test_a_record_cannot_show_negative_anything() -> None:
    with pytest.raises(ValidationError, match="negative delivery"):
        record(2020, delivered="-1")
    with pytest.raises(ValidationError, match="negative acres"):
        record(2020, acres="-1")
    with pytest.raises(ValidationError, match="negative curtailment"):
        record(2020, curtailed=-1)


def test_consumption_is_capped_by_what_the_crop_could_use() -> None:
    generous = record(2020, delivered="400")
    assert generous.consumed_af == generous.crop_requirement_af


def test_consumption_is_capped_by_what_was_delivered() -> None:
    lean = record(2020, delivered="20")
    assert lean.consumed_af < lean.crop_requirement_af
    assert lean.consumed_af == Decimal("9.0000")


def test_a_clean_ten_years_averages_out() -> None:
    study = analyse(ten_years())
    assert study.counted_years == 10
    assert study.average_af > Decimal("0")


def test_an_estimated_year_is_left_out() -> None:
    records = ten_years()
    records[3] = record(2018, provenance=Provenance.ESTIMATED)
    study = analyse(records)
    assert study.counted_years == 9
    assert "estimated" in study.finding_for(2018).reason


def test_a_void_year_is_left_out_too() -> None:
    records = ten_years()
    records[3] = record(2018, provenance=Provenance.VOID)
    assert analyse(records).counted_years == 9


def test_a_curtailed_year_is_not_representative() -> None:
    records = ten_years()
    records[5] = record(2020, curtailed=45)
    study = analyse(records)
    assert study.counted_years == 9
    assert "curtailed 45 days" in study.finding_for(2020).reason


def test_a_short_curtailment_does_not_disqualify_the_year() -> None:
    records = ten_years()
    records[5] = record(2020, curtailed=12)
    assert analyse(records).counted_years == 10


def test_a_curtailed_year_can_be_counted_if_the_applicant_insists() -> None:
    records = ten_years()
    records[5] = record(2020, curtailed=45)
    assert analyse(records, count_curtailed=True).counted_years == 10


def test_a_fallow_year_is_left_out() -> None:
    records = ten_years()
    records[2] = record(2017, crop=CropCode.FALLOW)
    study = analyse(records)
    assert "fallow" in study.finding_for(2017).reason
    assert study.counted_years == 9


def test_a_lapsed_calibration_in_one_july_lowers_the_average() -> None:
    clean = analyse(ten_years()).average_af
    records = ten_years()
    records[4] = record(2019, delivered="400")
    generous = analyse(records).average_af
    records[4] = record(2019, delivered="400", provenance=Provenance.ESTIMATED)
    unproven = analyse(records).average_af
    assert unproven <= generous
    assert clean <= generous


def test_too_few_usable_years_stops_the_study() -> None:
    records = [record(year, provenance=Provenance.ESTIMATED) for year in range(2015, 2025)]
    records[0] = record(2015)
    with pytest.raises(PolicyError, match="years of the study are usable"):
        analyse(records)


def test_a_study_with_no_record_at_all_is_refused() -> None:
    with pytest.raises(PolicyError, match="needs a delivery record"):
        analyse([])


def test_a_year_listed_twice_is_refused() -> None:
    with pytest.raises(ValidationError, match="lists a year twice"):
        analyse([*ten_years(), record(2020)])


def test_the_findings_come_back_in_year_order() -> None:
    study = analyse(list(reversed(ten_years())))
    assert [item.water_year for item in study.findings] == list(range(2015, 2025))


def test_asking_about_a_year_outside_the_study_is_refused() -> None:
    with pytest.raises(PolicyError, match="not in the study period"):
        analyse(ten_years()).finding_for(1999)


def test_the_excluded_years_are_listed_on_their_own() -> None:
    records = ten_years()
    records[3] = record(2018, provenance=Provenance.ESTIMATED)
    study = analyse(records)
    assert [item.water_year for item in study.excluded] == [2018]
    assert study.study_years == 10


def test_only_part_of_a_historical_use_may_be_moved() -> None:
    study = analyse(ten_years())
    assert transferable_af(study, Decimal("0.5")) < study.average_af
    assert transferable_af(study) == study.average_af


def test_an_impossible_share_is_refused() -> None:
    study = analyse(ten_years())
    with pytest.raises(ValidationError, match="not a share"):
        transferable_af(study, Decimal("1.5"))


def test_the_return_flow_is_what_was_not_consumed() -> None:
    assert return_flow_af(Decimal("160"), Decimal("60")) == Decimal("100")


def test_a_farm_cannot_consume_more_than_it_was_given() -> None:
    with pytest.raises(PolicyError, match="more than it was delivered"):
        return_flow_af(Decimal("60"), Decimal("160"))


def test_a_study_can_be_built_by_hand_for_a_report() -> None:
    study = HistoricalUse(findings=(), average_af=Decimal("0"))
    assert study.counted_years == 0
