import sqlite3
from collections.abc import Iterator

import pytest

from conector_odoo.domain.errors import MappingInUse, MappingInvalid, MappingNotFound
from conector_odoo.domain.mapping import Constant, Direct, MappingDefinition
from conector_odoo.infrastructure.mappings.repository import SqliteMappingRepository
from conector_odoo.infrastructure.migrations import open_admin_database
from tests.mapping.helpers import definition, rule


@pytest.fixture
def conn() -> Iterator[sqlite3.Connection]:
    connection = open_admin_database(":memory:")
    yield connection
    connection.close()


@pytest.fixture
def repo(conn: sqlite3.Connection) -> SqliteMappingRepository:
    return SqliteMappingRepository(conn)


def v(name: str = "m", value: str = "a") -> MappingDefinition:
    return definition(rule("t", Constant(value)), name=name)


async def test_first_save_is_version_one_and_round_trips(repo: SqliteMappingRepository) -> None:
    d = definition(rule("t.x", Direct("s", default=0), required=True), name="clients")
    stored = await repo.save_new_version(d)
    assert (stored.name, stored.version, stored.definition) == ("clients", 1, d)
    assert await repo.get("clients") == stored
    assert await repo.get("clients", 1) == stored


async def test_changed_definition_creates_next_version_per_name(
    repo: SqliteMappingRepository,
) -> None:
    assert (await repo.save_new_version(v("a", "1"))).version == 1
    assert (await repo.save_new_version(v("a", "2"))).version == 2
    assert (await repo.save_new_version(v("b", "1"))).version == 1
    latest = await repo.get("a")
    assert latest is not None and latest.version == 2
    first = await repo.get("a", 1)
    assert first is not None and first.definition == v("a", "1")


async def test_identical_to_latest_returns_latest_without_new_version(
    repo: SqliteMappingRepository,
) -> None:
    first = await repo.save_new_version(v())
    again = await repo.save_new_version(v())
    assert again == first
    assert len(await repo.list_versions("m")) == 1


async def test_reverting_to_an_old_definition_is_a_new_version(
    repo: SqliteMappingRepository,
) -> None:
    await repo.save_new_version(v("m", "1"))
    await repo.save_new_version(v("m", "2"))
    third = await repo.save_new_version(v("m", "1"))
    assert third.version == 3


async def test_get_unknown_returns_none(repo: SqliteMappingRepository) -> None:
    await repo.save_new_version(v())
    assert await repo.get("nope") is None
    assert await repo.get("m", 9) is None


async def test_list_latest_and_versions(repo: SqliteMappingRepository) -> None:
    await repo.save_new_version(v("b", "1"))
    await repo.save_new_version(v("a", "1"))
    await repo.save_new_version(v("a", "2"))
    latest = await repo.list_latest()
    assert [(m.name, m.version) for m in latest] == [("a", 2), ("b", 1)]
    assert [m.version for m in await repo.list_versions("a")] == [1, 2]
    assert await repo.list_versions("zzz") == []


async def test_delete_removes_every_version(repo: SqliteMappingRepository) -> None:
    await repo.save_new_version(v("a", "1"))
    await repo.save_new_version(v("a", "2"))
    await repo.delete("a")
    assert await repo.get("a") is None
    with pytest.raises(MappingNotFound):
        await repo.delete("a")


def reference(conn: sqlite3.Connection, mapping_id: int) -> None:
    now = "2024-01-01T00:00:00+00:00"
    conn.execute(
        "INSERT INTO connection_profiles (id, name, type, base_url, auth_method, created_at, "
        "updated_at) VALUES (1, 'p', 'rest', 'https://x', 'none', ?, ?)",
        (now, now),
    )
    conn.execute(
        "INSERT INTO sync_jobs (name, source_profile_id, target_profile_id, mapping_id, "
        "direction, upsert_key, created_at, updated_at) VALUES ('j', 1, 1, ?, 'one_way', 'id', "
        "?, ?)",
        (mapping_id, now, now),
    )
    conn.commit()


async def test_delete_is_refused_while_any_version_is_referenced_by_a_job(
    repo: SqliteMappingRepository, conn: sqlite3.Connection
) -> None:
    await repo.save_new_version(v("a", "1"))
    await repo.save_new_version(v("a", "2"))
    reference(conn, 1)  # the OLD version
    with pytest.raises(MappingInUse):
        await repo.delete("a")
    assert len(await repo.list_versions("a")) == 2


async def test_corrupt_stored_json_is_reported_not_silently_dropped(
    repo: SqliteMappingRepository, conn: sqlite3.Connection
) -> None:
    conn.execute(
        "INSERT INTO mappings (name, version, definition_json, created_at) "
        "VALUES ('bad', 1, '{\"nope\": 1}', '2024-01-01T00:00:00+00:00')"
    )
    with pytest.raises(MappingInvalid):
        await repo.get("bad")
