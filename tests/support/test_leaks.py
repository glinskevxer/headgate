"""The leak guard has to be able to find a leak, or it proves nothing."""

from __future__ import annotations

import sqlite3

from headgate.store.db import Database
from tests.support import leaks


def test_a_closed_connection_leaves_nothing_behind() -> None:
    label = "positive control: closed"
    leaks.TRACKER.working_on(label)
    with Database.in_memory().open():
        pass
    assert leaks.TRACKER.leaked_here(label) == []


def test_a_leaked_connection_is_reported() -> None:
    label = "positive control: leaked"
    leaks.TRACKER.working_on(label)
    connection = Database.in_memory().connect()
    found = leaks.TRACKER.leaked_here(label)
    assert len(found) == 1
    assert "never closed" in found[0]
    connection.close()
    assert leaks.TRACKER.leaked_here(label) == []


def test_the_tracker_survives_two_connections_at_the_same_address() -> None:
    label = "positive control: reused address"
    leaks.TRACKER.working_on(label)
    first = Database.in_memory().connect()
    leaks.TRACKER.forget(label)
    second = Database.in_memory().connect()
    second.close()
    assert leaks.TRACKER.leaked_here(label) == []
    first.close()


def test_the_tracking_connection_is_still_an_ordinary_connection() -> None:
    with Database.in_memory().open() as connection:
        assert isinstance(connection, sqlite3.Connection)
        connection.execute("CREATE TABLE a (id INTEGER PRIMARY KEY)")


def test_installing_twice_is_harmless() -> None:
    leaks.install()
    leaks.install()
    assert leaks.TRACKER.installed
