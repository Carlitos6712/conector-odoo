import sqlite3
from collections.abc import Iterator

import pytest

from conector_odoo.domain.errors import ProfileInUse, ProfileNameTaken, ProfileNotFound
from conector_odoo.domain.profiles import AuthMethod, ConnectionProfile, ProfileType
from conector_odoo.infrastructure.migrations import open_admin_database
from conector_odoo.infrastructure.profiles.repository import SqliteConnectionProfileRepository


@pytest.fixture
def conn() -> Iterator[sqlite3.Connection]:
    connection = open_admin_database(":memory:")
    yield connection
    connection.close()


@pytest.fixture
def repo(conn: sqlite3.Connection) -> SqliteConnectionProfileRepository:
    return SqliteConnectionProfileRepository(conn)


def rest(name: str = "suwe") -> ConnectionProfile:
    return ConnectionProfile(
        id=None,
        name=name,
        type=ProfileType.REST,
        base_url="https://api.suwe.test",
        auth_method=AuthMethod.OAUTH2_CLIENT_CREDENTIALS,
        extra_headers={"X-Tenant": "acme"},
        tls_verify=False,
        timeout_seconds=12.5,
        token_url="https://auth.suwe.test/token",
        scope="read",
        secret_fields=frozenset({"client_id", "client_secret"}),
    )


async def test_add_and_get_round_trip(repo: SqliteConnectionProfileRepository) -> None:
    saved = await repo.add(rest(), b"blob")
    assert saved.id is not None
    assert saved.created_at is not None
    stored = await repo.get(saved.id)
    assert stored is not None
    assert stored.profile == saved
    assert stored.profile.extra_headers == {"X-Tenant": "acme"}
    assert stored.profile.tls_verify is False
    assert stored.profile.token_url == "https://auth.suwe.test/token"
    assert stored.secrets_blob == b"blob"


async def test_odoo_fields_round_trip(repo: SqliteConnectionProfileRepository) -> None:
    odoo = ConnectionProfile(
        id=None,
        name="odoo",
        type=ProfileType.ODOO,
        base_url="https://odoo.test",
        auth_method=AuthMethod.API_KEY,
        odoo_db="prod",
        odoo_login="bot@x.test",
    )
    saved = await repo.add(odoo, None)
    stored = await repo.get(saved.id or 0)
    assert stored is not None
    assert (stored.profile.odoo_db, stored.profile.odoo_login) == ("prod", "bot@x.test")
    assert stored.secrets_blob is None


async def test_secrets_are_only_stored_in_the_blob_column(
    repo: SqliteConnectionProfileRepository, conn: sqlite3.Connection
) -> None:
    marker = b"opaque-ciphertext"
    await repo.add(rest(), marker)
    row = conn.execute("SELECT secrets_blob, options_json FROM connection_profiles").fetchone()
    assert row[0] == marker
    assert "client_secret" in row[1]  # only the NAMES of the secrets are kept in clear
    # The blob lives in exactly one column: no other column of any table may contain it.
    tables = [
        r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'").fetchall()
    ]
    for table in tables:
        columns = [r[1] for r in conn.execute(f'PRAGMA table_info("{table}")').fetchall()]
        for column in columns:
            if (table, column) == ("connection_profiles", "secrets_blob"):
                continue
            for (value,) in conn.execute(f'SELECT "{column}" FROM "{table}"').fetchall():
                raw = value if isinstance(value, bytes) else str(value).encode()
                assert marker not in raw, f"secret leaked into {table}.{column}"
    assert conn.execute(
        "SELECT COUNT(*) FROM connection_profiles WHERE instr(secrets_blob, ?) > 0", (marker,)
    ).fetchone() == (1,)


async def test_name_must_be_unique(repo: SqliteConnectionProfileRepository) -> None:
    await repo.add(rest("dup"), None)
    with pytest.raises(ProfileNameTaken):
        await repo.add(rest("dup"), None)


async def test_update_replaces_fields_keeps_created_at(
    repo: SqliteConnectionProfileRepository,
) -> None:
    saved = await repo.add(rest(), b"one")
    changed = await repo.update(
        ConnectionProfile(**{**vars_of(saved), "name": "renamed", "timeout_seconds": 5.0}), b"two"
    )
    assert changed.name == "renamed"
    assert changed.created_at == saved.created_at
    stored = await repo.get(saved.id or 0)
    assert stored is not None
    assert stored.secrets_blob == b"two"


async def test_update_to_taken_name_conflicts(repo: SqliteConnectionProfileRepository) -> None:
    await repo.add(rest("a"), None)
    second = await repo.add(rest("b"), None)
    with pytest.raises(ProfileNameTaken):
        await repo.update(ConnectionProfile(**{**vars_of(second), "name": "a"}), None)


async def test_update_missing_profile(repo: SqliteConnectionProfileRepository) -> None:
    with pytest.raises(ProfileNotFound):
        await repo.update(ConnectionProfile(**{**vars_of(rest()), "id": 99}), None)


async def test_list_and_delete(repo: SqliteConnectionProfileRepository) -> None:
    first = await repo.add(rest("a"), None)
    await repo.add(rest("b"), None)
    assert [s.profile.name for s in await repo.list()] == ["a", "b"]
    await repo.delete(first.id or 0)
    assert [s.profile.name for s in await repo.list()] == ["b"]
    assert await repo.get(first.id or 0) is None


async def test_delete_missing_profile(repo: SqliteConnectionProfileRepository) -> None:
    with pytest.raises(ProfileNotFound):
        await repo.delete(123)


async def test_delete_profile_in_use_is_refused(
    repo: SqliteConnectionProfileRepository, conn: sqlite3.Connection
) -> None:
    saved = await repo.add(rest(), None)
    conn.execute(
        "INSERT INTO resources (profile_id, name, created_at) VALUES (?, 'customers', 'now')",
        (saved.id,),
    )
    with pytest.raises(ProfileInUse):
        await repo.delete(saved.id or 0)


def vars_of(profile: ConnectionProfile) -> dict[str, object]:
    import dataclasses

    return {f.name: getattr(profile, f.name) for f in dataclasses.fields(profile)}
