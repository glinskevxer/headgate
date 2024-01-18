import pytest

from headgate.errors import ValidationError
from headgate.ids import AccountNumber, DecreeNumber, DeviceTag, DitchCode, TurnoutCode


def test_a_ditch_code_is_letters_and_maybe_a_number() -> None:
    assert str(DitchCode.parse("l2")) == "L2"
    assert DitchCode("MAIN").text == "MAIN"


def test_a_ditch_code_refuses_a_station_suffix() -> None:
    with pytest.raises(ValidationError, match="ditch code"):
        DitchCode("L2-14")


def test_a_turnout_code_names_its_lateral_and_station() -> None:
    turnout = TurnoutCode.parse("l2-14")
    assert turnout.ditch == DitchCode("L2")
    assert turnout.station == 14
    assert str(turnout) == "L2-14"


def test_a_turnout_code_without_a_station_is_refused() -> None:
    with pytest.raises(ValidationError, match="turnout code"):
        TurnoutCode("L2")


def test_a_device_tag_carries_its_kind_and_its_site() -> None:
    tag = DeviceTag.parse("weir-l2-14")
    assert tag.kind_word == "WEIR"
    assert tag.site == "L2-14"


def test_a_device_tag_may_sit_on_a_whole_ditch() -> None:
    assert DeviceTag("FLUME-MAIN").site == "MAIN"


def test_an_unknown_device_kind_is_refused() -> None:
    with pytest.raises(ValidationError, match="device tag"):
        DeviceTag("PITOT-L2-14")


def test_a_decree_number_carries_the_adjudication() -> None:
    decree = DecreeNumber.parse("cda-1889-14")
    assert decree.district == "CDA"
    assert decree.adjudication_year == 1889
    assert decree.sequence == 14


def test_a_decree_number_needs_all_three_parts() -> None:
    with pytest.raises(ValidationError, match="decree number"):
        DecreeNumber("CDA-1889")


def test_account_numbers_print_padded_and_sort_by_value() -> None:
    assert str(AccountNumber(118)) == "00118"
    assert sorted([AccountNumber(9), AccountNumber(2)]) == [AccountNumber(2), AccountNumber(9)]


def test_account_numbers_parse_from_what_the_counter_writes() -> None:
    assert AccountNumber.parse(" #118 ") == AccountNumber(118)


@pytest.mark.parametrize("text", ["", "abc", "12x"])
def test_a_non_numeric_account_is_refused(text: str) -> None:
    with pytest.raises(ValidationError, match="account number"):
        AccountNumber.parse(text)


def test_an_account_outside_the_book_is_refused() -> None:
    with pytest.raises(ValidationError, match="outside the book"):
        AccountNumber(0)
