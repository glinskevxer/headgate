import sqlite3

import pytest

from headgate.errors import StoreError
from headgate.store.plans import (
    HOT_QUERIES,
    check_hot_queries,
    plan_for,
    require_index,
    scanning_queries,
)


def test_every_hot_query_is_answered_off_an_index(book: sqlite3.Connection) -> None:
    assert scanning_queries(book) == ()


def test_the_hot_queries_all_have_a_plan(book: sqlite3.Connection) -> None:
    plans = check_hot_queries(book)
    assert len(plans) == len(HOT_QUERIES)
    for _, plan in plans:
        assert plan.steps


def test_a_query_on_an_unindexed_column_scans(book: sqlite3.Connection) -> None:
    plan = plan_for(book, "SELECT * FROM account WHERE name = ?", ("Alma Peterson",))
    assert plan.scans_a_table
    assert not plan.uses_an_index


def test_a_query_on_a_key_uses_the_index(book: sqlite3.Connection) -> None:
    plan = require_index(book, "SELECT * FROM account WHERE number = ?", (118,))
    assert plan.uses_an_index
    assert "account" in plan.describe()


def test_insisting_on_an_index_over_a_scan_is_refused(book: sqlite3.Connection) -> None:
    with pytest.raises(StoreError, match="this query scans"):
        require_index(book, "SELECT * FROM account WHERE name = ?", ("Alma Peterson",))


def test_a_query_the_planner_will_not_explain_is_reported(book: sqlite3.Connection) -> None:
    with pytest.raises(StoreError, match="would not explain"):
        plan_for(book, "SELECT * FROM nothing_at_all")


def test_a_sort_the_index_cannot_help_with_shows_in_the_plan(
    book: sqlite3.Connection,
) -> None:
    plan = plan_for(book, "SELECT * FROM account ORDER BY name")
    assert plan.sorts


def test_the_reading_query_is_answered_off_the_key(book: sqlite3.Connection) -> None:
    name, sql, parameters = HOT_QUERIES[0]
    plan = plan_for(book, sql, parameters)
    assert "reading" in plan.describe()
    assert plan.uses_an_index
    assert name.startswith("readings")
