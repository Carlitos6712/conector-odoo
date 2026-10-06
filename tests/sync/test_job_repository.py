import sqlite3
from collections.abc import Iterator
from datetime import UTC, datetime

import pytest

from conector_odoo.domain.errors import (
    MappingInUse,
    MappingNotFound,
    ProfileNotFound,
    SyncJobInUse,
    SyncJobNameTaken,
    SyncJobNotFound,
)
from conector_odoo.domain.mapping import Constant
from conector_odoo.domain.records import RecordFilter
from conector_odoo.domain.sync import (
    ConflictRule,
    Direction,
    MappingRef,
    ScheduleTrigger,
    WebhookTrigger,
)
from conector_odoo.infrastructure.mappings.repository import SqliteMappingRepository
from conector_odoo.infrastructure.migrations import open_admin_database
from conector_odoo.infrastructure.sync.jobs import SqliteSyncJobRepository
from tests.mapping.helpers import definition, rule
from tests.sync.helpers import make_job

NOW = "2026-01-01T00:00:00+00:00"


@pytest.fixture
def conn() -> Iterator[sqlite3.Connection]:
    connection = open_admin_database(":memory:")
    for pid, name in ((1, "odoo"), (2, "suwe")):
        connection.execute(
            "INSERT INTO connection_profiles (id, name, type, base_url, auth_method, created_at, "
            "updated_at) VALUES (?, ?, 'rest', 'https://x', 'none', ?, ?)",
            (pid, name, NOW, NOW),
        )
    yield connection
    connection.close()


async def seed_mappings(conn: sqlite3.Connection) -> SqliteMappingRepository:
    repo = SqliteMappingRepository(conn)
    for name in ("fwd", "rev"):
        await repo.save_new_version(definition(rule("t", Constant("a")), name=name))
    return repo


async def test_round_trip_all_fields(conn: sqlite3.Connection) -> None:
    await seed_mappings(conn)
    repo = SqliteSyncJobRepository(conn)
    job = make_job(
        direction=Direction.BIDIRECTIONAL,
        upsert_key="field:email",
        conflict_rule=ConflictRule.NEWEST_WINS,
        source_updated_field="write_date",
        target_updated_field="updated",
        trigger=ScheduleTrigger("*/5 * * * *"),
        record_filter=RecordFilter(
            equals={"active": True},
            since=datetime(2026, 1, 1, tzinfo=UTC),
            raw={"domain": [["a", "=", 1]]},
        ),
        batch_size=250,
        enabled=False,
        mapping=MappingRef("fwd", 1),
    )
    saved = await repo.add(job)
    assert saved.id is not None
    assert saved == make_job_with_id(job, saved.id)
    assert await repo.get(saved.id) == saved
    assert await repo.list() == [saved]


def make_job_with_id(job, job_id: int):  # type: ignore[no-untyped-def]
    import dataclasses

    return dataclasses.replace(job, id=job_id)


async def test_webhook_trigger_round_trip_and_update(conn: sqlite3.Connection) -> None:
    await seed_mappings(conn)
    repo = SqliteSyncJobRepository(conn)
    saved = await repo.add(make_job(trigger=WebhookTrigger(("customer.updated",))))
    assert saved.trigger == WebhookTrigger(("customer.updated",))
    import dataclasses

    changed = await repo.update(dataclasses.replace(saved, name="renamed", batch_size=5))
    assert (changed.name, changed.batch_size) == ("renamed", 5)
    with pytest.raises(SyncJobNotFound):
        await repo.update(dataclasses.replace(saved, id=999))


async def test_unique_name_missing_profile_and_missing_mapping(conn: sqlite3.Connection) -> None:
    await seed_mappings(conn)
    repo = SqliteSyncJobRepository(conn)
    await repo.add(make_job())
    with pytest.raises(SyncJobNameTaken):
        await repo.add(make_job())
    with pytest.raises(ProfileNotFound):
        await repo.add(make_job(name="other", target_profile=99))
    with pytest.raises(MappingNotFound):
        await repo.add(make_job(name="third", mapping=MappingRef("ghost")))
    with pytest.raises(MappingNotFound):
        await repo.add(make_job(name="fourth", mapping=MappingRef("fwd", 7)))


async def test_job_blocks_deleting_either_of_its_mappings(conn: sqlite3.Connection) -> None:
    mappings = await seed_mappings(conn)
    jobs = SqliteSyncJobRepository(conn)
    await jobs.add(make_job(direction=Direction.BIDIRECTIONAL))
    with pytest.raises(MappingInUse):
        await mappings.delete("fwd")
    with pytest.raises(MappingInUse):
        await mappings.delete("rev")


async def test_delete_removes_job_and_xrefs_but_is_refused_when_runs_exist(
    conn: sqlite3.Connection,
) -> None:
    await seed_mappings(conn)
    repo = SqliteSyncJobRepository(conn)
    first = await repo.add(make_job())
    second = await repo.add(make_job(name="b"))
    assert first.id and second.id
    conn.execute(
        "INSERT INTO xref (job_id, resource, source_id, target_id, updated_at) "
        "VALUES (?, 'customers', '1', '9', ?)",
        (first.id, NOW),
    )
    conn.execute(
        "INSERT INTO sync_runs (job_id, status, trigger, started_at) "
        "VALUES (?, 'succeeded', 'manual', ?)",
        (second.id, NOW),
    )
    await repo.delete(first.id)
    assert await repo.get(first.id) is None
    assert conn.execute("SELECT COUNT(*) FROM xref").fetchone()[0] == 0
    with pytest.raises(SyncJobInUse):
        await repo.delete(second.id)
    with pytest.raises(SyncJobNotFound):
        await repo.delete(first.id)
