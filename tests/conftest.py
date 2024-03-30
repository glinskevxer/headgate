"""Fixtures every test layer shares."""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator

import pytest

from headgate.store.db import Database
from headgate.store.migrations import migrate


@pytest.fixture
def book() -> Iterator[sqlite3.Connection]:
    """A migrated district book held in memory."""

    with Database.in_memory().open() as connection:
        migrate(connection)
        yield connection
