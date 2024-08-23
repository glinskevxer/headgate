"""Catching connections nobody closed.

Python 3.13 raises a ResourceWarning when a sqlite3 connection is collected
still open, and this suite runs warnings as errors, so a leak that is invisible
on 3.12 turns into a failure on 3.13 against whichever test happened to be
running when the collector got to it. That is a miserable thing to debug from a
build log, so the leak is caught here instead, on whatever version is running.

Every connection gets a token of its own and the table is keyed on the token,
never on the object or its id. A leaked connection is freed when the test that
made it goes out of scope and CPython hands the same address straight to the
next allocation, so an id keyed table reports a clean suite while the leaks are
still there.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from itertools import count
from typing import Any

_tokens = count(1)


class TrackedConnection(sqlite3.Connection):
    """A connection that tells the tracker when it is opened and closed."""

    def __init__(self, *arguments: Any, **keywords: Any) -> None:
        super().__init__(*arguments, **keywords)
        self.headgate_token = next(_tokens)
        TRACKER.opened(self.headgate_token)

    def close(self) -> None:
        TRACKER.closed(self.headgate_token)
        super().close()


@dataclass
class Tracker:
    """Which connections are open, and what was running when they opened."""

    open_connections: dict[int, str] = field(default_factory=dict)
    label: str = "before any test"
    installed: bool = False

    def opened(self, token: int) -> None:
        self.open_connections[token] = self.label

    def closed(self, token: int) -> None:
        self.open_connections.pop(token, None)

    def working_on(self, label: str) -> None:
        self.label = label

    def leaks(self) -> list[str]:
        return sorted(
            f"a connection opened by {where} was never closed"
            for where in self.open_connections.values()
        )

    def leaked_here(self, label: str) -> list[str]:
        return [
            f"a connection opened by {where} was never closed"
            for where in self.open_connections.values()
            if where == label
        ]

    def forget(self, label: str) -> None:
        for token, where in list(self.open_connections.items()):
            if where == label:
                self.open_connections.pop(token, None)


TRACKER = Tracker()

_real_connect = sqlite3.connect


def install() -> None:
    """Point sqlite3.connect at the tracking subclass."""

    if TRACKER.installed:
        return

    def connect(*arguments: Any, **keywords: Any) -> sqlite3.Connection:
        keywords.setdefault("factory", TrackedConnection)
        connection: sqlite3.Connection = _real_connect(*arguments, **keywords)
        return connection

    sqlite3.connect = connect  # type: ignore[assignment]
    TRACKER.installed = True


def uninstall() -> None:
    sqlite3.connect = _real_connect
    TRACKER.installed = False
