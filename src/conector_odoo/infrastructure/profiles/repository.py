"""SQLite ``ConnectionProfileRepository`` over the ``connection_profiles`` table.

Secrets are stored only in ``secrets_blob`` (already encrypted by the vault). ``options_json``
holds non-secret type-specific settings plus the names of the stored secrets.
"""

import asyncio
import json
import sqlite3
import threading
from datetime import UTC, datetime
from typing import Any

from conector_odoo.domain.errors import ProfileInUse, ProfileNameTaken, ProfileNotFound
from conector_odoo.domain.profiles import (
    AuthMethod,
    ConnectionProfile,
    ProfileType,
    StoredProfile,
)

StoredProfiles = list[StoredProfile]  # the ``list`` method below shadows the builtin in the class

_COLUMNS = (
    "id, name, type, base_url, auth_method, secrets_blob, extra_headers_json, tls_verify, "
    "timeout_seconds, options_json, created_at, updated_at"
)


class SqliteConnectionProfileRepository:
    """Runs the (tiny) synchronous queries in a worker thread under a lock; the connection is
    the shared admin database opened by ``open_admin_database``."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn
        self._lock = threading.Lock()

    async def add(
        self, profile: ConnectionProfile, secrets_blob: bytes | None
    ) -> ConnectionProfile:
        return await asyncio.to_thread(self._add, profile, secrets_blob)

    async def update(
        self, profile: ConnectionProfile, secrets_blob: bytes | None
    ) -> ConnectionProfile:
        return await asyncio.to_thread(self._update, profile, secrets_blob)

    async def get(self, profile_id: int) -> StoredProfile | None:
        return await asyncio.to_thread(self._get, profile_id)

    async def list(self) -> StoredProfiles:
        return await asyncio.to_thread(self._list)

    async def delete(self, profile_id: int) -> None:
        await asyncio.to_thread(self._delete, profile_id)

    def _add(self, profile: ConnectionProfile, blob: bytes | None) -> ConnectionProfile:
        now = datetime.now(UTC).isoformat()
        with self._lock:
            try:
                cursor = self._conn.execute(
                    "INSERT INTO connection_profiles (name, type, base_url, auth_method, "
                    "secrets_blob, extra_headers_json, tls_verify, timeout_seconds, options_json, "
                    "created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (*_values(profile, blob), now, now),
                )
            except sqlite3.IntegrityError as exc:
                raise _translate(exc, profile.name) from exc
            new_id = cursor.lastrowid
            assert new_id is not None
            return self._read(new_id).profile

    def _update(self, profile: ConnectionProfile, blob: bytes | None) -> ConnectionProfile:
        if profile.id is None:
            raise ProfileNotFound("cannot update a profile without an id")
        with self._lock:
            try:
                cursor = self._conn.execute(
                    "UPDATE connection_profiles SET name = ?, type = ?, base_url = ?, "
                    "auth_method = ?, secrets_blob = ?, extra_headers_json = ?, tls_verify = ?, "
                    "timeout_seconds = ?, options_json = ?, updated_at = ? WHERE id = ?",
                    (*_values(profile, blob), datetime.now(UTC).isoformat(), profile.id),
                )
            except sqlite3.IntegrityError as exc:
                raise _translate(exc, profile.name) from exc
            if cursor.rowcount == 0:
                raise ProfileNotFound(f"connection profile {profile.id} not found")
            return self._read(profile.id).profile

    def _get(self, profile_id: int) -> StoredProfile | None:
        with self._lock:
            row = self._conn.execute(
                f"SELECT {_COLUMNS} FROM connection_profiles WHERE id = ?", (profile_id,)
            ).fetchone()
        return None if row is None else _to_stored(row)

    def _list(self) -> StoredProfiles:
        with self._lock:
            rows = self._conn.execute(
                f"SELECT {_COLUMNS} FROM connection_profiles ORDER BY id"
            ).fetchall()
        return [_to_stored(row) for row in rows]

    def _delete(self, profile_id: int) -> None:
        with self._lock:
            try:
                cursor = self._conn.execute(
                    "DELETE FROM connection_profiles WHERE id = ?", (profile_id,)
                )
            except sqlite3.IntegrityError as exc:
                raise ProfileInUse(
                    f"connection profile {profile_id} is used by resources or jobs"
                ) from exc
        if cursor.rowcount == 0:
            raise ProfileNotFound(f"connection profile {profile_id} not found")

    def _read(self, profile_id: int) -> StoredProfile:
        row = self._conn.execute(
            f"SELECT {_COLUMNS} FROM connection_profiles WHERE id = ?", (profile_id,)
        ).fetchone()
        return _to_stored(row)


def _translate(exc: sqlite3.IntegrityError, name: str) -> Exception:
    if "UNIQUE" in str(exc):
        return ProfileNameTaken(f"a connection profile named {name!r} already exists")
    return exc


def _values(profile: ConnectionProfile, blob: bytes | None) -> tuple[Any, ...]:
    options = {
        "odoo_db": profile.odoo_db,
        "odoo_login": profile.odoo_login,
        "token_url": profile.token_url,
        "username": profile.username,
        "scope": profile.scope,
        "api_key_header": profile.api_key_header,
        "secret_fields": sorted(profile.secret_fields),
    }
    return (
        profile.name,
        profile.type.value,
        profile.base_url,
        profile.auth_method.value,
        blob,
        json.dumps(profile.extra_headers),
        int(profile.tls_verify),
        profile.timeout_seconds,
        json.dumps(options),
    )


def _to_stored(row: tuple[Any, ...]) -> StoredProfile:
    options = json.loads(row[9])
    profile = ConnectionProfile(
        id=row[0],
        name=row[1],
        type=ProfileType(row[2]),
        base_url=row[3],
        auth_method=AuthMethod(row[4]),
        extra_headers=json.loads(row[6]),
        tls_verify=bool(row[7]),
        timeout_seconds=row[8],
        odoo_db=options.get("odoo_db"),
        odoo_login=options.get("odoo_login"),
        token_url=options.get("token_url"),
        username=options.get("username"),
        scope=options.get("scope"),
        api_key_header=options.get("api_key_header", "X-API-Key"),
        secret_fields=frozenset(options.get("secret_fields", ())),
        created_at=datetime.fromisoformat(row[10]),
        updated_at=datetime.fromisoformat(row[11]),
    )
    return StoredProfile(profile=profile, secrets_blob=row[5])
