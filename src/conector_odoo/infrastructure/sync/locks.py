"""One lock per SQLite connection, shared by every repository that uses it.

The admin connection is shared across threads (``check_same_thread=False``); repositories run
their blocking work in worker threads, so all of them must serialise on the same lock.
``sqlite3.Connection`` cannot be weakly referenced, so the registry keeps the connection alive:
a handful of long-lived admin connections per process, which is the intended use.
"""

import sqlite3
import threading

_locks: dict[int, tuple[sqlite3.Connection, threading.RLock]] = {}
_guard = threading.Lock()


def connection_lock(conn: sqlite3.Connection) -> threading.RLock:
    with _guard:
        entry = _locks.get(id(conn))
        if entry is None:
            entry = _locks[id(conn)] = (conn, threading.RLock())
        return entry[1]
