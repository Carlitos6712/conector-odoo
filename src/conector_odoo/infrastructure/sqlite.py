"""Shared SQLite plumbing for the idempotency and webhook-event stores.

One connection guarded by a ``threading.Lock`` (``check_same_thread=False``) serialises access;
the work is tiny, so callers run the synchronous helpers in a worker thread (``asyncio.to_thread``)
only to keep the event loop free. The database file is created with mode 0600 (and tightened if it
already existed); a parent directory created here is 0700, because stored rows may hold PII.
"""

import asyncio
import os
import sqlite3
import threading
from pathlib import Path
from typing import Any


class SqliteDatabase:
    """Lock-guarded autocommit connection that applies ``schema`` once on creation."""

    def __init__(self, path: str, schema: str) -> None:
        if path != ":memory:":
            prepare_private_file(Path(path))
        self.lock = threading.Lock()
        self.conn = sqlite3.connect(path, check_same_thread=False, isolation_level=None)
        self.conn.execute(schema)

    def execute(self, sql: str, params: tuple[Any, ...] = ()) -> int:
        """Run one statement under the lock and return its ``rowcount``."""
        with self.lock:
            return self.conn.execute(sql, params).rowcount

    async def close(self) -> None:
        await asyncio.to_thread(self._close)

    def _close(self) -> None:
        with self.lock:
            self.conn.close()


def prepare_private_file(path: Path) -> None:
    """Create the database file as 0600 (parent 0700 if created here); tighten an existing one."""
    parent = path.parent
    if not parent.exists():
        parent.mkdir(parents=True, exist_ok=True)
        parent.chmod(0o700)
    if not path.exists():
        os.close(os.open(path, os.O_RDWR | os.O_CREAT, 0o600))
    path.chmod(0o600)
