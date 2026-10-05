"""A whole sync world on fakes: real SQLite repositories, in-memory endpoints, a fake clock."""

import sqlite3
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

from conector_odoo.application.sync_runner import RunnerConfig, SyncRunner
from conector_odoo.domain.mapping import Direct, Lower, Transform
from conector_odoo.domain.records import FieldSpec, FieldType, ResourceSchema
from conector_odoo.domain.sync import SyncJob
from conector_odoo.domain.sync_runs import RunFilter, SyncRun
from conector_odoo.infrastructure.mappings.repository import SqliteMappingRepository
from conector_odoo.infrastructure.migrations import open_admin_database
from conector_odoo.infrastructure.sync.jobs import SqliteSyncJobRepository
from conector_odoo.infrastructure.sync.runs import SqliteSyncRunRepository, SqliteXRefRepository
from tests.mapping.helpers import definition, rule
from tests.sync.helpers import make_job
from tests.unit.fakes_records import InMemoryRecordEndpoint

T0 = datetime(2026, 5, 1, 12, 0, tzinfo=UTC)
NOW = T0.isoformat()


def schema(name: str, *fields: str) -> ResourceSchema:
    return ResourceSchema(name, name, tuple(FieldSpec(f, FieldType.STRING) for f in fields))


class FakeClock:
    def __init__(self) -> None:
        self.now = T0

    def __call__(self) -> datetime:
        return self.now

    def advance(self, **kwargs: float) -> None:
        self.now += timedelta(**kwargs)


@dataclass
class World:
    conn: sqlite3.Connection
    odoo: InMemoryRecordEndpoint  # profile 1, resource "customers" (side A)
    rest: InMemoryRecordEndpoint  # profile 2, resource "clients" (side B)
    clock: FakeClock = field(default_factory=FakeClock)
    sleeps: list[float] = field(default_factory=list)
    on_sleep: Callable[[], Awaitable[None]] | None = None
    config: RunnerConfig = field(default_factory=RunnerConfig)
    auth_failure: BaseException | None = None

    def __post_init__(self) -> None:
        self.jobs = SqliteSyncJobRepository(self.conn)
        self.runs = SqliteSyncRunRepository(self.conn)
        self.xrefs = SqliteXRefRepository(self.conn)
        self.mappings = SqliteMappingRepository(self.conn)
        self.rebuild()

    def rebuild(self) -> None:
        """New runner instance over the same storage (simulates a process restart)."""

        async def factory(profile_id: int) -> Any:
            if self.auth_failure is not None:
                raise self.auth_failure
            return {1: self.odoo, 2: self.rest}[profile_id]

        async def sleep(seconds: float) -> None:
            self.sleeps.append(seconds)
            if self.on_sleep is not None:
                await self.on_sleep()

        self.runner = SyncRunner(
            self.jobs,
            self.runs,
            self.xrefs,
            self.mappings,
            factory,
            clock=self.clock,
            sleep=sleep,
            config=self.config,
        )

    async def add_job(self, **overrides: Any) -> SyncJob:
        await self.mappings.save_new_version(
            definition(
                rule("full_name", Direct("name")),
                rule("email", Transform(Direct("email"), (Lower(),)), required=True),
                name="fwd",
            )
        )
        await self.mappings.save_new_version(
            definition(
                rule("name", Direct("full_name")),
                rule("email", Direct("email")),
                name="rev",
            )
        )
        return await self.jobs.add(make_job(**overrides))

    async def last_run(self) -> SyncRun:
        return (await self.runs.list_runs(RunFilter(), 1))[0]


def build_world(**config: Any) -> World:
    conn = open_admin_database(":memory:")
    for pid, name in ((1, "odoo"), (2, "suwe")):
        conn.execute(
            "INSERT INTO connection_profiles (id, name, type, base_url, auth_method, created_at, "
            "updated_at) VALUES (?, ?, 'rest', 'https://x', 'none', ?, ?)",
            (pid, name, NOW, NOW),
        )
    odoo = InMemoryRecordEndpoint({"customers": schema("customers", "name", "email")})
    rest = InMemoryRecordEndpoint({"clients": schema("clients", "full_name", "email")})
    return World(conn, odoo, rest, config=RunnerConfig(**config))
