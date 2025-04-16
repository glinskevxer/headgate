"""Asking SQLite how it means to answer a question.

Every query in this package runs against a district's whole history, and the
difference between an index and a scan is the difference between a report that
prints and a report the clerk gives up on. The planner will tell anybody who
asks which it is going to do, so the queries that matter are checked rather
than hoped about.

What is checked here is the shape of the plan, not how long it took. Timing a
query on a test database with forty rows in it measures the machine, not the
query, and would go green on a table scan every time.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from ..errors import StoreError
from .db import query


@dataclass(frozen=True, slots=True)
class QueryPlan:
    """What the planner said it would do."""

    sql: str
    steps: tuple[str, ...]

    @property
    def uses_an_index(self) -> bool:
        """Whether the planner looks the rows up rather than reading them all.

        A rowid primary key does not say INDEX at all, it says INTEGER PRIMARY
        KEY, and a lookup on one is as good as an index. Reading the plan for
        the word INDEX alone reports a scan on the fastest query in the book.
        """

        wanted = (
            "USING INDEX",
            "USING COVERING INDEX",
            "USING INTEGER PRIMARY KEY",
            "USING PRIMARY KEY",
        )
        return any(mark in step for step in self.steps for mark in wanted)

    @property
    def scans_a_table(self) -> bool:
        return any(step.startswith("SCAN") for step in self.steps)

    @property
    def sorts(self) -> bool:
        return any("USE TEMP B-TREE" in step for step in self.steps)

    def describe(self) -> str:
        return " / ".join(self.steps)


def plan_for(connection: sqlite3.Connection, sql: str, parameters: Sequence[Any] = ()) -> QueryPlan:
    """Ask the planner what it would do with a query."""

    try:
        rows = query(connection, f"EXPLAIN QUERY PLAN {sql}", parameters)
    except sqlite3.Error as exc:
        raise StoreError(f"the planner would not explain that query: {exc}") from exc
    return QueryPlan(sql=sql, steps=tuple(str(row["detail"]) for row in rows))


def require_index(
    connection: sqlite3.Connection, sql: str, parameters: Sequence[Any] = ()
) -> QueryPlan:
    """Insist a query is answered off an index rather than a scan."""

    plan = plan_for(connection, sql, parameters)
    if not plan.uses_an_index:
        raise StoreError(f"this query scans: {sql}\n{plan.describe()}")
    return plan


HOT_QUERIES: tuple[tuple[str, str, tuple[Any, ...]], ...] = (
    (
        "readings for a device over a span",
        "SELECT * FROM reading WHERE device_tag = ? AND taken_at < ? ORDER BY taken_at",
        ("WEIR-L2-14", "2025-10-01 00:00:00"),
    ),
    (
        "orders running at a moment",
        "SELECT * FROM water_order WHERE run_from <= ? AND run_to > ?"
        " AND status IN ('accepted', 'reduced')",
        ("2025-07-04 12:00:00", "2025-07-04 12:00:00"),
    ),
    (
        "the journal for one subject",
        "SELECT * FROM journal_entry WHERE subject = ? ORDER BY sequence",
        ("L2-14",),
    ),
    (
        "one account's bills",
        "SELECT * FROM assessment_bill WHERE account_number = ? ORDER BY water_year",
        (118,),
    ),
    (
        "a year's payments",
        "SELECT * FROM payment WHERE received_on >= ? AND received_on < ?",
        ("2025-01-01", "2026-01-01"),
    ),
    (
        "the gage record over a span",
        "SELECT * FROM gage_day WHERE gage_code = ? AND day >= ? AND day < ? ORDER BY day",
        ("SANP-1", "2025-06-01", "2025-07-01"),
    ),
    (
        "curtailments standing at a moment",
        "SELECT * FROM curtailment_notice WHERE effective_at <= ?"
        " AND (lifted_at IS NULL OR lifted_at > ?)",
        ("2025-07-04 12:00:00", "2025-07-04 12:00:00"),
    ),
)


def check_hot_queries(connection: sqlite3.Connection) -> tuple[tuple[str, QueryPlan], ...]:
    """Every query the office runs every day, with the plan behind it."""

    return tuple(
        (name, plan_for(connection, sql, parameters)) for name, sql, parameters in HOT_QUERIES
    )


def scanning_queries(connection: sqlite3.Connection) -> tuple[str, ...]:
    """The hot queries the planner would answer with a table scan."""

    return tuple(name for name, plan in check_hot_queries(connection) if not plan.uses_an_index)
