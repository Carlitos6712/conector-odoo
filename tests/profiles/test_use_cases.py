import dataclasses
import sqlite3
from collections.abc import Iterator

import pytest
from cryptography.fernet import Fernet

from conector_odoo.application.profiles import (
    CreateProfile,
    DeleteProfile,
    GetProfile,
    ListProfiles,
    ProfileView,
    TestConnection,
    UpdateProfile,
)
from conector_odoo.domain.errors import (
    ProfileNameTaken,
    ProfileNotFound,
    VaultDecryptionError,
    VaultNotConfigured,
)
from conector_odoo.domain.profiles import (
    AuthMethod,
    ConnectionProfile,
    ConnectionTestResult,
    ProbeStep,
    ProfileType,
    Secrets,
)
from conector_odoo.infrastructure.migrations import open_admin_database
from conector_odoo.infrastructure.profiles.repository import SqliteConnectionProfileRepository
from conector_odoo.infrastructure.profiles.vault import FernetVault

SECRET = "never-show-this-value"


@pytest.fixture
def conn() -> Iterator[sqlite3.Connection]:
    connection = open_admin_database(":memory:")
    yield connection
    connection.close()


class Env:
    def __init__(self, conn: sqlite3.Connection, vault: FernetVault) -> None:
        self.repo = SqliteConnectionProfileRepository(conn)
        self.vault = vault
        self.create = CreateProfile(self.repo, vault)
        self.update = UpdateProfile(self.repo, vault)
        self.get = GetProfile(self.repo)
        self.list = ListProfiles(self.repo)
        self.delete = DeleteProfile(self.repo)


@pytest.fixture
def env(conn: sqlite3.Connection) -> Env:
    return Env(conn, FernetVault(Fernet.generate_key().decode()))


def draft(name: str = "suwe") -> ConnectionProfile:
    return ConnectionProfile(
        id=None,
        name=name,
        type=ProfileType.REST,
        base_url="https://api.test",
        auth_method=AuthMethod.API_KEY,
    )


def flatten(view: ProfileView) -> str:
    return f"{view!r} {view!s} {dataclasses.asdict(view)}"


async def test_create_returns_view_without_secrets(env: Env) -> None:
    view = await env.create.execute(draft(), Secrets(api_key=SECRET))
    assert view.id is not None
    assert view.has_secret["api_key"] is True
    assert view.has_secret["token"] is False
    assert SECRET not in flatten(view)


async def test_secret_is_encrypted_at_rest(env: Env) -> None:
    view = await env.create.execute(draft(), Secrets(api_key=SECRET))
    stored = await env.repo.get(view.id)
    assert stored is not None
    assert stored.secrets_blob is not None
    assert SECRET.encode() not in stored.secrets_blob
    assert env.vault.decrypt(stored.secrets_blob).api_key == SECRET


async def test_create_without_secrets_needs_no_key(conn: sqlite3.Connection) -> None:
    env = Env(conn, FernetVault(None))
    view = await env.create.execute(draft(), None)
    assert not any(view.has_secret.values())


async def test_create_with_secrets_and_no_key_fails_clearly(conn: sqlite3.Connection) -> None:
    env = Env(conn, FernetVault(None))
    with pytest.raises(VaultNotConfigured):
        await env.create.execute(draft(), Secrets(api_key=SECRET))
    assert await env.list.execute() == []  # nothing half-saved


async def test_duplicate_name_is_a_domain_error(env: Env) -> None:
    await env.create.execute(draft("dup"), None)
    with pytest.raises(ProfileNameTaken):
        await env.create.execute(draft("dup"), None)


async def test_get_and_list_never_expose_secrets(env: Env) -> None:
    created = await env.create.execute(draft("a"), Secrets(api_key=SECRET))
    await env.create.execute(draft("b"), None)
    fetched = await env.get.execute(created.id)
    listed = await env.list.execute()
    assert fetched.name == "a"
    assert [v.name for v in listed] == ["a", "b"]
    assert SECRET not in flatten(fetched) + "".join(flatten(v) for v in listed)


async def test_get_missing_profile(env: Env) -> None:
    with pytest.raises(ProfileNotFound):
        await env.get.execute(404)


async def test_update_keeps_secret_when_omitted(env: Env) -> None:
    created = await env.create.execute(draft(), Secrets(api_key=SECRET, client_id="cid"))
    updated = await env.update.execute(
        created.id, dataclasses.replace(draft(), base_url="https://new.test"), None
    )
    assert updated.base_url == "https://new.test"
    assert updated.has_secret["api_key"] is True
    stored = await env.repo.get(created.id)
    assert stored is not None
    assert stored.secrets_blob is not None
    assert env.vault.decrypt(stored.secrets_blob) == Secrets(api_key=SECRET, client_id="cid")


async def test_update_without_secrets_works_without_a_key(conn: sqlite3.Connection) -> None:
    with_key = Env(conn, FernetVault(Fernet.generate_key().decode()))
    created = await with_key.create.execute(draft(), Secrets(api_key=SECRET))
    no_key = Env(conn, FernetVault(None))
    updated = await no_key.update.execute(created.id, draft("renamed"), None)
    assert updated.name == "renamed"
    assert updated.has_secret["api_key"] is True


async def test_update_replaces_only_the_provided_secrets(env: Env) -> None:
    created = await env.create.execute(draft(), Secrets(api_key=SECRET, client_id="cid"))
    updated = await env.update.execute(created.id, draft(), Secrets(client_id="new", token="t"))
    assert {k for k, v in updated.has_secret.items() if v} == {"api_key", "client_id", "token"}
    stored = await env.repo.get(created.id)
    assert stored is not None
    assert stored.secrets_blob is not None
    assert env.vault.decrypt(stored.secrets_blob) == Secrets(
        api_key=SECRET, client_id="new", token="t"
    )


async def test_update_empty_string_clears_a_secret(env: Env) -> None:
    created = await env.create.execute(draft(), Secrets(api_key=SECRET))
    updated = await env.update.execute(created.id, draft(), Secrets(api_key=""))
    assert not any(updated.has_secret.values())
    stored = await env.repo.get(created.id)
    assert stored is not None
    assert stored.secrets_blob is None


async def test_update_with_wrong_key_cannot_merge_secrets(conn: sqlite3.Connection) -> None:
    first = Env(conn, FernetVault(Fernet.generate_key().decode()))
    created = await first.create.execute(draft(), Secrets(api_key=SECRET))
    other = Env(conn, FernetVault(Fernet.generate_key().decode()))
    with pytest.raises(VaultDecryptionError):
        await other.update.execute(created.id, draft(), Secrets(token="t"))


async def test_update_missing_profile(env: Env) -> None:
    with pytest.raises(ProfileNotFound):
        await env.update.execute(7, draft(), None)


async def test_update_to_a_taken_name_conflicts(env: Env) -> None:
    await env.create.execute(draft("a"), None)
    second = await env.create.execute(draft("b"), None)
    with pytest.raises(ProfileNameTaken):
        await env.update.execute(second.id, draft("a"), None)


async def test_delete(env: Env) -> None:
    created = await env.create.execute(draft(), None)
    await env.delete.execute(created.id)
    with pytest.raises(ProfileNotFound):
        await env.get.execute(created.id)
    with pytest.raises(ProfileNotFound):
        await env.delete.execute(created.id)


class RecordingProbe:
    def __init__(self, steps: list[ProbeStep]) -> None:
        self.steps = steps
        self.seen: list[tuple[ConnectionProfile, Secrets]] = []

    async def probe(self, profile: ConnectionProfile, secrets: Secrets) -> list[ProbeStep]:
        self.seen.append((profile, secrets))
        return self.steps


def ok(name: str) -> ProbeStep:
    return ProbeStep(name, True, "fine", None)


def bad(name: str) -> ProbeStep:
    return ProbeStep(name, False, "broke", "fix it")


def test_result_stops_at_the_first_failing_step() -> None:
    result = ConnectionTestResult.from_steps([ok("url_valid"), bad("reachable"), ok("tls")])
    assert result.ok is False
    assert result.failed_step == "reachable"
    assert [s.name for s in result.steps] == ["url_valid", "reachable"]


def test_result_ok_when_every_step_passes() -> None:
    result = ConnectionTestResult.from_steps([ok("url_valid"), ok("auth")])
    assert (result.ok, result.failed_step) == (True, None)


async def test_test_connection_by_id_uses_stored_secrets(env: Env) -> None:
    created = await env.create.execute(draft(), Secrets(api_key=SECRET))
    probe = RecordingProbe([ok("url_valid"), ok("auth")])
    use_case = TestConnection(env.repo, env.vault, {ProfileType.REST: probe})
    result = await use_case.test_saved(created.id)
    assert result.ok is True
    assert probe.seen[0][1] == Secrets(api_key=SECRET)
    assert SECRET not in repr(result)


async def test_test_connection_by_id_without_secrets_needs_no_key(conn: sqlite3.Connection) -> None:
    env = Env(conn, FernetVault(None))
    created = await env.create.execute(draft(), None)
    probe = RecordingProbe([bad("reachable")])
    use_case = TestConnection(env.repo, env.vault, {ProfileType.REST: probe})
    result = await use_case.test_saved(created.id)
    assert result.failed_step == "reachable"
    assert probe.seen[0][1] == Secrets()


async def test_test_connection_missing_profile(env: Env) -> None:
    use_case = TestConnection(env.repo, env.vault, {})
    with pytest.raises(ProfileNotFound):
        await use_case.test_saved(1)


async def test_test_connection_draft_does_not_persist(env: Env) -> None:
    probe = RecordingProbe([ok("url_valid")])
    use_case = TestConnection(env.repo, env.vault, {ProfileType.REST: probe})
    result = await use_case.test_draft(draft(), Secrets(token=SECRET))
    assert result.ok is True
    assert probe.seen[0][1].token == SECRET
    assert await env.list.execute() == []
