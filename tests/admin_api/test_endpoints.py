import sqlite3
from collections.abc import Iterator
from dataclasses import replace

import pytest

from conector_odoo.domain.errors import ProfileNotFound, RemoteUnavailable
from conector_odoo.domain.profiles import AuthMethod, ConnectionProfile, ProfileType, Secrets
from conector_odoo.infrastructure.endpoints import ProfileEndpoints
from conector_odoo.infrastructure.migrations import open_admin_database
from conector_odoo.infrastructure.profiles.repository import SqliteConnectionProfileRepository
from conector_odoo.infrastructure.profiles.vault import FernetVault
from conector_odoo.infrastructure.resources.repository import SqliteResourceCatalogRepository
from tests.admin_api.conftest import ENCRYPTION_KEY, admin_settings


@pytest.fixture
def conn() -> Iterator[sqlite3.Connection]:
    connection = open_admin_database(":memory:")
    yield connection
    connection.close()


def make(conn: sqlite3.Connection, key: str | None = ENCRYPTION_KEY) -> ProfileEndpoints:
    return ProfileEndpoints(
        SqliteConnectionProfileRepository(conn),
        SqliteResourceCatalogRepository(conn),
        FernetVault(key),
        admin_settings(),
    )


async def add_rest_profile(conn: sqlite3.Connection, secrets: Secrets | None = None) -> int:
    vault = FernetVault(ENCRYPTION_KEY)
    secrets = secrets or Secrets(token="a-bearer-token")
    saved = await SqliteConnectionProfileRepository(conn).add(
        ConnectionProfile(
            id=None,
            name="rest",
            type=ProfileType.REST,
            base_url="https://api.test",
            auth_method=AuthMethod.BEARER,
            secret_fields=secrets.present_fields(),
        ),
        vault.encrypt(secrets),
    )
    assert saved.id is not None
    return saved.id


async def test_endpoint_is_cached_per_profile_and_closed_once(conn: sqlite3.Connection) -> None:
    endpoints = make(conn)
    pid = await add_rest_profile(conn)
    first = await endpoints(pid)
    assert await endpoints(pid) is first
    await endpoints.aclose()
    assert await endpoints(pid) is not first  # a closed cache starts over


async def test_editing_a_profile_builds_a_fresh_endpoint(conn: sqlite3.Connection) -> None:
    endpoints = make(conn)
    pid = await add_rest_profile(conn)
    first = await endpoints(pid)
    repo = SqliteConnectionProfileRepository(conn)
    stored = await repo.get(pid)
    assert stored is not None
    await repo.update(replace(stored.profile, timeout_seconds=7), stored.secrets_blob)
    assert await endpoints(pid) is not first
    await endpoints.aclose()


async def test_missing_profile_and_missing_vault_key_fail_cleanly(conn: sqlite3.Connection) -> None:
    pid = await add_rest_profile(conn)
    with pytest.raises(ProfileNotFound):
        await make(conn)(999)
    with pytest.raises(RemoteUnavailable) as raised:
        await make(conn, key=None)(pid)
    assert "a-bearer-token" not in str(raised.value)
