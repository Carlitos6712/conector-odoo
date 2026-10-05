import sqlite3
from collections.abc import Iterator

import pytest

from conector_odoo.domain.errors import (
    CatalogResourceNotFound,
    ProfileInUse,
    ProfileNotFound,
    ResourceConfigInvalid,
)
from conector_odoo.domain.profiles import AuthMethod, ConnectionProfile, ProfileType
from conector_odoo.domain.resources import EndpointSpec, ResourceConfig, ResourceSource
from conector_odoo.infrastructure.migrations import open_admin_database
from conector_odoo.infrastructure.profiles.repository import SqliteConnectionProfileRepository
from conector_odoo.infrastructure.resources.repository import SqliteResourceCatalogRepository


@pytest.fixture
def conn() -> Iterator[sqlite3.Connection]:
    connection = open_admin_database(":memory:")
    yield connection
    connection.close()


@pytest.fixture
def catalog(conn: sqlite3.Connection) -> SqliteResourceCatalogRepository:
    return SqliteResourceCatalogRepository(conn)


async def make_profile(conn: sqlite3.Connection, name: str = "suwe") -> int:
    profiles = SqliteConnectionProfileRepository(conn)
    saved = await profiles.add(
        ConnectionProfile(
            id=None,
            name=name,
            type=ProfileType.REST,
            base_url="https://api.test",
            auth_method=AuthMethod.BEARER,
        ),
        None,
    )
    assert saved.id is not None
    return saved.id


def clients(label: str = "Clients") -> ResourceConfig:
    return ResourceConfig(
        name="organization.clients",
        label=label,
        list_endpoint=EndpointSpec("GET", "/organization/clients"),
        items_path="items",
    )


async def test_save_and_get_round_trip(
    conn: sqlite3.Connection, catalog: SqliteResourceCatalogRepository
) -> None:
    pid = await make_profile(conn)
    saved = await catalog.save(pid, clients(), ResourceSource.OPENAPI)
    assert saved.profile_id == pid
    assert saved.source is ResourceSource.OPENAPI
    assert saved.config == clients()
    assert saved.updated_at is not None
    assert await catalog.get(pid, "organization.clients") == saved
    assert await catalog.get(pid, "missing") is None


async def test_save_is_an_upsert_per_profile_and_name(
    conn: sqlite3.Connection, catalog: SqliteResourceCatalogRepository
) -> None:
    pid = await make_profile(conn)
    first = await catalog.save(pid, clients("Old"), ResourceSource.OPENAPI)
    second = await catalog.save(pid, clients("New"), ResourceSource.MANUAL)
    assert second.config.label == "New"
    assert second.source is ResourceSource.MANUAL
    assert len(await catalog.list(pid)) == 1
    assert second.updated_at >= first.updated_at


async def test_same_name_may_exist_in_two_profiles(
    conn: sqlite3.Connection, catalog: SqliteResourceCatalogRepository
) -> None:
    a, b = await make_profile(conn, "a"), await make_profile(conn, "b")
    await catalog.save(a, clients("A"), ResourceSource.MANUAL)
    await catalog.save(b, clients("B"), ResourceSource.MANUAL)
    assert [r.config.label for r in await catalog.list(a)] == ["A"]
    assert [r.config.label for r in await catalog.list(b)] == ["B"]


async def test_list_is_ordered_by_name(
    conn: sqlite3.Connection, catalog: SqliteResourceCatalogRepository
) -> None:
    pid = await make_profile(conn)
    for name in ("b", "a", "c"):
        cfg = ResourceConfig(name=name, label=name, list_endpoint=EndpointSpec("GET", f"/{name}"))
        await catalog.save(pid, cfg, ResourceSource.MANUAL)
    assert [r.config.name for r in await catalog.list(pid)] == ["a", "b", "c"]


async def test_delete_and_missing_delete(
    conn: sqlite3.Connection, catalog: SqliteResourceCatalogRepository
) -> None:
    pid = await make_profile(conn)
    await catalog.save(pid, clients(), ResourceSource.MANUAL)
    await catalog.delete(pid, "organization.clients")
    assert await catalog.list(pid) == []
    with pytest.raises(CatalogResourceNotFound):
        await catalog.delete(pid, "organization.clients")


async def test_saving_for_an_unknown_profile_is_refused(
    catalog: SqliteResourceCatalogRepository,
) -> None:
    with pytest.raises(ProfileNotFound):
        await catalog.save(999, clients(), ResourceSource.MANUAL)


async def test_deleting_a_profile_with_resources_is_refused_like_b2(
    conn: sqlite3.Connection, catalog: SqliteResourceCatalogRepository
) -> None:
    pid = await make_profile(conn)
    await catalog.save(pid, clients(), ResourceSource.MANUAL)
    with pytest.raises(ProfileInUse):
        await SqliteConnectionProfileRepository(conn).delete(pid)
    await catalog.delete(pid, "organization.clients")
    await SqliteConnectionProfileRepository(conn).delete(pid)  # now allowed


async def test_corrupt_stored_json_is_a_clear_domain_error(
    conn: sqlite3.Connection, catalog: SqliteResourceCatalogRepository
) -> None:
    pid = await make_profile(conn)
    conn.execute(
        "INSERT INTO resources (profile_id, name, config_json, created_at) "
        "VALUES (?, 'x', ?, 'now')",
        (pid, '{"version": 42}'),
    )
    with pytest.raises(ResourceConfigInvalid):
        await catalog.get(pid, "x")
