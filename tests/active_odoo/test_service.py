"""``ActiveOdooConnection``: activate/clear/restore with probe-before-swap and persistence."""

import sqlite3
from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Any

import pytest
from cryptography.fernet import Fernet

from conector_odoo.application.active_odoo import ActiveOdooConnection, OdooActivationLog
from conector_odoo.config import Settings
from conector_odoo.domain.active_odoo import OdooSource
from conector_odoo.domain.errors import (
    OdooActivationFailed,
    ProfileNotFound,
    ProfileValidationError,
)
from conector_odoo.domain.profiles import (
    AuthMethod,
    ConnectionProfile,
    ProbeStep,
    ProfileType,
    Secrets,
)
from conector_odoo.infrastructure.app_settings import SqliteAppSettings
from conector_odoo.infrastructure.migrations import open_admin_database
from conector_odoo.infrastructure.odoo.provider import OdooConnectionProvider
from conector_odoo.infrastructure.profiles.repository import SqliteConnectionProfileRepository
from conector_odoo.infrastructure.profiles.vault import FernetVault

NOW = datetime(2026, 5, 1, 12, 0, tzinfo=UTC)
ENV = {
    "odoo_url": "https://env.odoo.test",
    "odoo_db": "envdb",
    "odoo_user": "envbot",
    "odoo_api_key": "env-api-key-0123456789",
}


class FakeClient:
    def __init__(self, label: str) -> None:
        self.label = label
        self.closed = False

    async def aclose(self) -> None:
        self.closed = True


class FakeProbe:
    def __init__(self) -> None:
        self.ok = True
        self.calls: list[str] = []

    async def probe(self, profile: ConnectionProfile, secrets: Secrets) -> list[ProbeStep]:
        self.calls.append(profile.name)
        if self.ok:
            return [ProbeStep("auth", True, "authenticated as uid 2")]
        return [
            ProbeStep("reachable", True, "ok"),
            ProbeStep("auth", False, "Odoo rejected the credentials", "Check the API key."),
        ]


class World:
    def __init__(self, conn: sqlite3.Connection, **env: Any) -> None:
        self.conn = conn
        settings = Settings(  # type: ignore[call-arg]
            _env_file=None, webhook_secret="whsec-test-secret-123", **env
        )
        self.settings = settings
        self.vault = FernetVault(Fernet.generate_key().decode())
        self.profiles = SqliteConnectionProfileRepository(conn)
        self.built: list[FakeClient] = []

        def make(label: str) -> Any:
            client = FakeClient(label)
            self.built.append(client)
            return client

        self.provider = OdooConnectionProvider(
            settings,
            profile_client_factory=lambda profile, secrets: make(f"profile:{profile.name}"),
            env_client_factory=lambda: make("env"),
        )
        self.probe = FakeProbe()
        self.log = OdooActivationLog(SqliteAppSettings(conn), clock=lambda: NOW)
        self.service = ActiveOdooConnection(
            self.profiles,
            self.vault,
            {ProfileType.ODOO: self.probe},
            self.provider,
            self.log,
            settings,
        )

    async def add_profile(self, name: str = "prod", **overrides: Any) -> int:
        values: dict[str, Any] = {
            "id": None,
            "name": name,
            "type": ProfileType.ODOO,
            "base_url": "https://odoo.example.com",
            "auth_method": AuthMethod.API_KEY,
            "odoo_db": "prod",
            "odoo_login": "bot@example.com",
        }
        values.update(overrides)
        secrets = Secrets(api_key="profile-api-key-0123456789")
        blob = self.vault.encrypt(secrets)
        saved = await self.profiles.add(
            ConnectionProfile(**values, secret_fields=secrets.present_fields()), blob
        )
        assert saved.id is not None
        return saved.id

    def live(self) -> list[str]:
        return [c.label for c in self.built if not c.closed]


@pytest.fixture
def conn() -> Iterator[sqlite3.Connection]:
    connection = open_admin_database(":memory:")
    yield connection
    connection.close()


# -- startup resolution matrix ---------------------------------------------------------------


async def test_startup_without_any_odoo_configuration_is_source_none(
    conn: sqlite3.Connection,
) -> None:
    world = World(conn)
    await world.service.restore()
    status = await world.service.status()
    assert status.source is OdooSource.NONE
    assert status.status == "not_configured"
    assert world.provider.current is None


async def test_startup_with_all_four_env_vars_uses_env(conn: sqlite3.Connection) -> None:
    world = World(conn, **ENV)
    await world.service.restore()
    status = await world.service.status()
    assert status.source is OdooSource.ENV
    assert status.profile_id is None
    assert (status.base_url, status.db, status.login) == (
        "https://env.odoo.test",
        "envdb",
        "envbot",
    )
    assert world.live() == ["env"]


async def test_startup_with_partial_env_is_source_none(conn: sqlite3.Connection) -> None:
    world = World(conn, odoo_url="https://env.odoo.test", odoo_db="envdb")
    await world.service.restore()
    assert (await world.service.status()).source is OdooSource.NONE


async def test_startup_prefers_the_persisted_active_profile_over_env(
    conn: sqlite3.Connection,
) -> None:
    world = World(conn, **ENV)
    profile_id = await world.add_profile()
    await world.log.record_activation(profile_id)
    await world.service.restore()
    status = await world.service.status()
    assert status.source is OdooSource.PROFILE
    assert status.profile_id == profile_id
    assert status.profile_name == "prod"
    assert status.db == "prod"
    assert status.login == "bot@example.com"
    assert world.live() == ["profile:prod"]
    assert world.probe.calls == []  # startup never blocks on a remote probe


async def test_startup_with_a_deleted_active_profile_falls_back_to_env(
    conn: sqlite3.Connection,
) -> None:
    world = World(conn, **ENV)
    await world.log.record_activation(999)
    await world.service.restore()
    status = await world.service.status()
    assert status.source is OdooSource.ENV
    assert status.status == "fallback"
    assert status.warning is not None and "999" in status.warning


async def test_startup_with_a_deleted_active_profile_and_no_env_is_none(
    conn: sqlite3.Connection,
) -> None:
    world = World(conn)
    await world.log.record_activation(999)
    await world.service.restore()
    status = await world.service.status()
    assert status.source is OdooSource.NONE
    assert status.warning is not None


async def test_startup_with_an_undecryptable_profile_falls_back_without_crashing(
    conn: sqlite3.Connection,
) -> None:
    world = World(conn, **ENV)
    profile_id = await world.add_profile()
    await world.log.record_activation(profile_id)
    world.vault = FernetVault(Fernet.generate_key().decode())  # a different key
    world.service = ActiveOdooConnection(
        world.profiles,
        world.vault,
        {ProfileType.ODOO: world.probe},
        world.provider,
        world.log,
        world.settings,
    )
    await world.service.restore()
    status = await world.service.status()
    assert status.source is OdooSource.ENV
    assert status.warning is not None
    assert "profile-api-key" not in status.warning


async def test_startup_with_a_non_odoo_active_profile_falls_back(
    conn: sqlite3.Connection,
) -> None:
    world = World(conn)
    rest = await world.profiles.add(
        ConnectionProfile(
            id=None,
            name="rest",
            type=ProfileType.REST,
            base_url="https://api.example.com",
            auth_method=AuthMethod.API_KEY,
        ),
        None,
    )
    await world.log.record_activation(rest.id or 0)
    await world.service.restore()
    assert (await world.service.status()).source is OdooSource.NONE


# -- activate ---------------------------------------------------------------------------------


async def test_activate_probes_swaps_and_persists(conn: sqlite3.Connection) -> None:
    world = World(conn, **ENV)
    await world.service.restore()
    profile_id = await world.add_profile()
    status = await world.service.activate(profile_id)
    assert status.source is OdooSource.PROFILE
    assert status.profile_id == profile_id
    assert status.last_connected_at == NOW
    assert world.probe.calls == ["prod"]
    assert world.live() == ["profile:prod"]  # the env client was closed after the swap
    record = await world.log.load()
    assert record.active_profile_id == profile_id
    assert record.last_connected_profile_id == profile_id
    assert record.last_connected_at == NOW
    assert record.per_profile[profile_id] == NOW


async def test_activation_survives_a_restart(conn: sqlite3.Connection) -> None:
    first = World(conn)
    profile_id = await first.add_profile()
    await first.service.activate(profile_id)
    second = World(conn)  # same database, fresh process
    second.vault = first.vault
    second.service = ActiveOdooConnection(
        second.profiles,
        second.vault,
        {ProfileType.ODOO: second.probe},
        second.provider,
        second.log,
        second.settings,
    )
    await second.service.restore()
    status = await second.service.status()
    assert status.source is OdooSource.PROFILE
    assert status.profile_id == profile_id


async def test_a_failed_probe_refuses_and_keeps_the_old_connection(
    conn: sqlite3.Connection,
) -> None:
    world = World(conn, **ENV)
    await world.service.restore()
    profile_id = await world.add_profile()
    world.probe.ok = False
    with pytest.raises(OdooActivationFailed) as caught:
        await world.service.activate(profile_id)
    assert caught.value.failed_step == "auth"
    assert "Odoo rejected the credentials" in str(caught.value)
    assert world.provider.current is not None
    assert world.provider.current.source is OdooSource.ENV
    assert world.live() == ["env"]  # the candidate was built, then discarded
    record = await world.log.load()
    assert record.active_profile_id is None
    assert record.last_connected_at is None


async def test_activating_a_missing_profile_is_not_found(conn: sqlite3.Connection) -> None:
    world = World(conn)
    with pytest.raises(ProfileNotFound):
        await world.service.activate(42)


async def test_only_odoo_profiles_can_be_activated(conn: sqlite3.Connection) -> None:
    world = World(conn)
    rest = await world.profiles.add(
        ConnectionProfile(
            id=None,
            name="rest",
            type=ProfileType.REST,
            base_url="https://api.example.com",
            auth_method=AuthMethod.API_KEY,
        ),
        None,
    )
    with pytest.raises(ProfileValidationError, match="odoo"):
        await world.service.activate(rest.id or 0)


async def test_switching_between_profiles_closes_the_previous_client(
    conn: sqlite3.Connection,
) -> None:
    world = World(conn)
    first = await world.add_profile("one")
    second = await world.add_profile("two")
    await world.service.activate(first)
    await world.service.activate(second)
    assert world.live() == ["profile:two"]
    assert (await world.service.status()).profile_id == second


# -- clear ------------------------------------------------------------------------------------


async def test_clear_falls_back_to_env_when_present(conn: sqlite3.Connection) -> None:
    world = World(conn, **ENV)
    profile_id = await world.add_profile()
    await world.service.activate(profile_id)
    status = await world.service.clear()
    assert status.source is OdooSource.ENV
    assert world.live() == ["env"]
    assert (await world.log.load()).active_profile_id is None


async def test_clear_without_env_leaves_none_and_remembers_the_last_connection(
    conn: sqlite3.Connection,
) -> None:
    world = World(conn)
    profile_id = await world.add_profile()
    await world.service.activate(profile_id)
    status = await world.service.clear()
    assert status.source is OdooSource.NONE
    assert status.last_connected_at == NOW
    assert world.live() == []
    assert world.provider.current is None


async def test_activating_a_profile_overrides_the_env_connection(
    conn: sqlite3.Connection,
) -> None:
    world = World(conn, **ENV)
    await world.service.restore()
    assert (await world.service.status()).source is OdooSource.ENV
    await world.service.activate(await world.add_profile())
    assert (await world.service.status()).source is OdooSource.PROFILE
