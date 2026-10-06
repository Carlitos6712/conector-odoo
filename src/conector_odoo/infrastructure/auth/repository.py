"""SQLite adapters for admin users, sessions and the failed-login throttle.

All three share the admin connection (autocommit, ``isolation_level=None``: every statement is
its own transaction, which these single-statement writes rely on) and its per-connection lock.
"""

import asyncio
import math
import sqlite3
from datetime import UTC, datetime, timedelta
from typing import Any

from conector_odoo.domain.auth import AdminSession, AdminUser, Role
from conector_odoo.domain.errors import AdminUsernameTaken, AdminUserNotFound
from conector_odoo.infrastructure.sync.locks import connection_lock

AdminUsers = list[AdminUser]  # the ``list`` method below shadows the builtin
_USER_COLUMNS = "id, username, role, created_at"


def _ts(value: datetime) -> str:
    return value.astimezone(UTC).isoformat()


def _dt(value: str) -> datetime:
    return datetime.fromisoformat(value)


def _to_user(row: tuple[Any, ...]) -> AdminUser:
    return AdminUser(row[0], row[1], Role(row[2]), _dt(row[3]))


class SqliteAdminUserRepository:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn
        self._lock = connection_lock(conn)

    async def add(
        self, username: str, password_hash: str, role: Role, created_at: datetime
    ) -> AdminUser:
        return await asyncio.to_thread(self._add, username, password_hash, role, created_at)

    async def get(self, user_id: int) -> AdminUser | None:
        return await asyncio.to_thread(self._get, user_id)

    async def get_credentials(self, username: str) -> tuple[AdminUser, str] | None:
        return await asyncio.to_thread(self._get_credentials, username)

    async def list(self) -> list[AdminUser]:
        return await asyncio.to_thread(self._list)

    async def count(self) -> int:
        return await asyncio.to_thread(self._scalar, "SELECT COUNT(*) FROM admin_users")

    async def count_admins(self) -> int:
        return await asyncio.to_thread(
            self._scalar, "SELECT COUNT(*) FROM admin_users WHERE role = 'admin'"
        )

    async def update(
        self, user_id: int, *, role: Role | None = None, password_hash: str | None = None
    ) -> AdminUser:
        return await asyncio.to_thread(self._update, user_id, role, password_hash)

    async def delete(self, user_id: int) -> None:
        await asyncio.to_thread(self._delete, user_id)

    def _add(
        self, username: str, password_hash: str, role: Role, created_at: datetime
    ) -> AdminUser:
        with self._lock:
            try:
                cursor = self._conn.execute(
                    "INSERT INTO admin_users (username, password_hash, role, created_at) "
                    "VALUES (?, ?, ?, ?)",
                    (username, password_hash, role.value, _ts(created_at)),
                )
            except sqlite3.IntegrityError:
                raise AdminUsernameTaken("that username is already taken") from None
            assert cursor.lastrowid is not None
            return AdminUser(cursor.lastrowid, username, role, created_at)

    def _get(self, user_id: int) -> AdminUser | None:
        with self._lock:
            row = self._conn.execute(
                f"SELECT {_USER_COLUMNS} FROM admin_users WHERE id = ?", (user_id,)
            ).fetchone()
        return None if row is None else _to_user(row)

    def _get_credentials(self, username: str) -> tuple[AdminUser, str] | None:
        with self._lock:
            row = self._conn.execute(
                f"SELECT {_USER_COLUMNS}, password_hash FROM admin_users "
                "WHERE lower(username) = lower(?)",
                (username,),
            ).fetchone()
        return None if row is None else (_to_user(row), row[4])

    def _list(self) -> AdminUsers:
        with self._lock:
            rows = self._conn.execute(
                f"SELECT {_USER_COLUMNS} FROM admin_users ORDER BY lower(username)"
            ).fetchall()
        return [_to_user(row) for row in rows]

    def _scalar(self, sql: str) -> int:
        with self._lock:
            value: int = self._conn.execute(sql).fetchone()[0]
        return value

    def _update(self, user_id: int, role: Role | None, password_hash: str | None) -> AdminUser:
        with self._lock:
            if role is not None:
                self._conn.execute(
                    "UPDATE admin_users SET role = ? WHERE id = ?", (role.value, user_id)
                )
            if password_hash is not None:
                self._conn.execute(
                    "UPDATE admin_users SET password_hash = ? WHERE id = ?",
                    (password_hash, user_id),
                )
            row = self._conn.execute(
                f"SELECT {_USER_COLUMNS} FROM admin_users WHERE id = ?", (user_id,)
            ).fetchone()
        if row is None:
            raise AdminUserNotFound(f"admin user {user_id} not found")
        return _to_user(row)

    def _delete(self, user_id: int) -> None:
        with self._lock:
            # The FK cascade needs ``PRAGMA foreign_keys``; delete the sessions explicitly so the
            # guarantee does not depend on how the connection was opened.
            self._conn.execute("DELETE FROM admin_sessions WHERE user_id = ?", (user_id,))
            cursor = self._conn.execute("DELETE FROM admin_users WHERE id = ?", (user_id,))
        if cursor.rowcount == 0:
            raise AdminUserNotFound(f"admin user {user_id} not found")


class SqliteSessionStore:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn
        self._lock = connection_lock(conn)

    async def create(self, session: AdminSession) -> None:
        await asyncio.to_thread(self._create, session)

    async def get(self, token_hash: str) -> AdminSession | None:
        return await asyncio.to_thread(self._get, token_hash)

    async def touch(self, token_hash: str, last_seen_at: datetime) -> None:
        await asyncio.to_thread(
            self._run,
            "UPDATE admin_sessions SET last_seen_at = ? WHERE token_hash = ?",
            (_ts(last_seen_at), token_hash),
        )

    async def delete(self, token_hash: str) -> None:
        await asyncio.to_thread(
            self._run, "DELETE FROM admin_sessions WHERE token_hash = ?", (token_hash,)
        )

    async def delete_for_user(self, user_id: int) -> None:
        await asyncio.to_thread(
            self._run, "DELETE FROM admin_sessions WHERE user_id = ?", (user_id,)
        )

    async def purge_expired(self, now: datetime) -> int:
        return await asyncio.to_thread(
            self._run, "DELETE FROM admin_sessions WHERE expires_at <= ?", (_ts(now),)
        )

    def _run(self, sql: str, params: tuple[Any, ...]) -> int:
        with self._lock:
            return self._conn.execute(sql, params).rowcount

    def _create(self, session: AdminSession) -> None:
        self._run(
            "INSERT INTO admin_sessions (token_hash, user_id, csrf_token, created_at, expires_at,"
            " last_seen_at) VALUES (?, ?, ?, ?, ?, ?)",
            (
                session.token_hash,
                session.user_id,
                session.csrf_token,
                _ts(session.created_at),
                _ts(session.expires_at),
                _ts(session.last_seen_at),
            ),
        )

    def _get(self, token_hash: str) -> AdminSession | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT token_hash, user_id, csrf_token, created_at, expires_at, last_seen_at "
                "FROM admin_sessions WHERE token_hash = ?",
                (token_hash,),
            ).fetchone()
        if row is None:
            return None
        return AdminSession(row[0], row[1], row[2], _dt(row[3]), _dt(row[4]), _dt(row[5]))


class SqliteLoginThrottle:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn
        self._lock = connection_lock(conn)

    async def retry_after(self, key: str, now: datetime) -> int:
        return await asyncio.to_thread(self._retry_after, key, now)

    async def record_failure(
        self, key: str, now: datetime, *, max_failures: int, lock_seconds: int
    ) -> None:
        await asyncio.to_thread(self._record_failure, key, now, max_failures, lock_seconds)

    async def reset(self, key: str) -> None:
        await asyncio.to_thread(self._reset, key)

    def _retry_after(self, key: str, now: datetime) -> int:
        with self._lock:
            row = self._conn.execute(
                "SELECT locked_until FROM login_attempts WHERE key = ?", (key,)
            ).fetchone()
        if row is None or row[0] is None:
            return 0
        remaining = (_dt(row[0]) - now).total_seconds()
        return math.ceil(remaining) if remaining > 0 else 0

    def _record_failure(
        self, key: str, now: datetime, max_failures: int, lock_seconds: int
    ) -> None:
        with self._lock:
            row = self._conn.execute(
                "SELECT failures, last_failure_at FROM login_attempts WHERE key = ?", (key,)
            ).fetchone()
            failures = 0
            # Failures older than one lock window (or a served lock) no longer count.
            if row is not None and now - _dt(row[1]) <= timedelta(seconds=lock_seconds):
                failures = row[0]
            failures += 1
            locked_until = (
                _ts(now + timedelta(seconds=lock_seconds)) if failures >= max_failures else None
            )
            self._conn.execute(
                "INSERT INTO login_attempts (key, failures, locked_until, last_failure_at) "
                "VALUES (?, ?, ?, ?) ON CONFLICT (key) DO UPDATE SET failures = excluded.failures,"
                " locked_until = excluded.locked_until, last_failure_at = excluded.last_failure_at",
                (key, failures, locked_until, _ts(now)),
            )

    def _reset(self, key: str) -> None:
        with self._lock:
            self._conn.execute("DELETE FROM login_attempts WHERE key = ?", (key,))
