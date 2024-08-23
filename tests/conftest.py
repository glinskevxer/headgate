"""Fixtures every test layer shares."""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator

import pytest

from headgate.store.db import Database
from headgate.store.migrations import migrate
from tests.support import leaks

leaks.install()


@pytest.fixture(autouse=True)
def no_leaked_connections(request: pytest.FixtureRequest) -> Iterator[None]:
    """Fail a test that walks away from an open connection."""

    label = request.node.nodeid
    leaks.TRACKER.working_on(label)
    yield
    leaks.TRACKER.working_on("teardown")
    found = leaks.TRACKER.leaked_here(label)
    if found:
        leaks.TRACKER.forget(label)
        pytest.fail("\n".join(found))


@pytest.fixture
def book() -> Iterator[sqlite3.Connection]:
    """A migrated district book held in memory."""

    with Database.in_memory().open() as connection:
        migrate(connection)
        yield connection
