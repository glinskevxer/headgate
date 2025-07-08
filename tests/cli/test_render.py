from decimal import Decimal

import pytest

from headgate.cli.render import (
    Align,
    Column,
    as_json,
    field_list,
    hours,
    plural,
    rate,
    render_table,
    truncate,
    volume,
    yes_no,
)


def test_a_rate_prints_to_three_places() -> None:
    assert rate(Decimal("1.5")) == "1.500"
    assert rate(None) == "-"


def test_a_volume_prints_to_two_places() -> None:
    assert volume(Decimal("12.3456")) == "12.35"
    assert volume(None) == "-"


def test_hours_print_to_one_place() -> None:
    assert hours(Decimal("24")) == "24.0"
    assert hours(None) == "-"


def test_a_table_lines_its_columns_up() -> None:
    columns = [Column("turnout"), Column("rate", Align.RIGHT)]
    text = render_table(columns, [["L2-14", "1.500"], ["MAIN-3", "12.000"]])
    lines = text.splitlines()
    assert lines[0].startswith("turnout")
    assert lines[1].startswith("-------")
    assert lines[2].endswith(" 1.500")


def test_a_column_is_as_wide_as_its_widest_cell() -> None:
    columns = [Column("a")]
    text = render_table(columns, [["a much longer cell"]])
    assert len(text.splitlines()[1]) == len("a much longer cell")


def test_a_row_that_does_not_fit_is_refused() -> None:
    with pytest.raises(ValueError, match="does not fit"):
        render_table([Column("a")], [["one", "two"]])


def test_a_table_with_no_rows_still_prints_its_head() -> None:
    text = render_table([Column("turnout")], [])
    assert text.splitlines()[0] == "turnout"
    assert len(text.splitlines()) == 2


def test_a_field_list_lines_the_labels_up() -> None:
    text = field_list([("district", "Sanpete"), ("water year", "2025")])
    assert text.splitlines()[0].startswith("district  ")
    assert "water year  2025" in text


def test_an_empty_field_list_prints_nothing() -> None:
    assert field_list([]) == ""


def test_counts_read_right_on_a_report_line() -> None:
    assert plural(1, "order") == "1 order"
    assert plural(2, "order") == "2 orders"
    assert plural(2, "ditch", "ditches") == "2 ditches"


def test_flags_print_as_words() -> None:
    assert yes_no(True) == "yes"
    assert yes_no(False) == "no"


def test_a_long_note_is_cut_with_an_ellipsis() -> None:
    assert truncate("the lateral was already full", 12) == "the later..."
    assert truncate("short", 12) == "short"


def test_truncating_to_nothing_useful_is_refused() -> None:
    with pytest.raises(ValueError, match="fewer than four"):
        truncate("anything", 3)


def test_a_report_comes_out_as_json() -> None:
    import json

    columns = [Column("turnout"), Column("rate", Align.RIGHT)]
    text = as_json([("district", "Sanpete")], columns, [["L2-14", "1.500"]])
    found = json.loads(text)
    assert found["summary"]["district"] == "Sanpete"
    assert found["columns"] == ["turnout", "rate"]
    assert found["rows"][0]["rate"] == "1.500"


def test_every_value_in_the_json_is_a_string() -> None:
    import json

    columns = [Column("acre feet", Align.RIGHT)]
    found = json.loads(as_json([("total", "12.50")], columns, [["12.50"]]))
    assert isinstance(found["rows"][0]["acre feet"], str)


def test_a_row_that_does_not_fit_the_columns_is_refused() -> None:
    with pytest.raises(ValueError, match="does not fit the columns"):
        as_json([], [Column("a")], [["one", "two"]])


def test_a_report_with_no_rows_still_comes_out() -> None:
    import json

    found = json.loads(as_json([("district", "Sanpete")], [Column("a")], []))
    assert found["rows"] == []
