import sqlite3
from datetime import timedelta

import pytest

from conector_odoo.domain.auth import AdminSession, Role
from conector_odoo.domain.errors import AdminUsernameTaken, AdminUserNotFound
from tests.auth.helpers import T0, AuthWorld


async def test_users_are_unique_case_insensitively(world: AuthWorld) -> None:
    await world.users.add("Alice", "h", Role.ADMIN, T0)
    with pytest.raises(AdminUsernameTaken):
        await world.users.add("alice", "h2", Role.OPERATOR, T0)


async def test_credentials_lookup_is_case_insensitive(world: AuthWorld) -> None:
    added = await world.users.add("Alice", "hash-1", Role.OPERATOR, T0)
    found = await world.users.get_credentials("ALICE")
    assert found is not None
    user, password_hash = found
    assert (user, password_hash) == (added, "hash-1")
    assert await world.users.get_credentials("bob") is None


async def test_update_and_delete_user(world: AuthWorld) -> None:
    user = await world.users.add("alice", "h", Role.OPERATOR, T0)
    updated = await world.users.update(user.id, role=Role.ADMIN, password_hash="h2")
    assert updated.role is Role.ADMIN
    found = await world.users.get_credentials("alice")
    assert found is not None and found[1] == "h2"
    await world.users.delete(user.id)
    assert await world.users.get(user.id) is None
    with pytest.raises(AdminUserNotFound):
        await world.users.delete(user.id)
    with pytest.raises(AdminUserNotFound):
        await world.users.update(user.id, role=Role.ADMIN)


async def test_counts(world: AuthWorld) -> None:
    await world.users.add("a", "h", Role.ADMIN, T0)
    await world.users.add("b", "h", Role.OPERATOR, T0)
    assert (await world.users.count(), await world.users.count_admins()) == (2, 1)


def make_session(user_id: int, token_hash: str = "t1", ttl_minutes: int = 60) -> AdminSession:
    return AdminSession(token_hash, user_id, "csrf", T0, T0 + timedelta(minutes=ttl_minutes), T0)


async def test_session_roundtrip_touch_and_delete(world: AuthWorld) -> None:
    user = await world.users.add("alice", "h", Role.ADMIN, T0)
    await world.sessions.create(make_session(user.id))
    assert await world.sessions.get("t1") == make_session(user.id)
    await world.sessions.touch("t1", T0 + timedelta(minutes=5))
    loaded = await world.sessions.get("t1")
    assert loaded is not None and loaded.last_seen_at == T0 + timedelta(minutes=5)
    await world.sessions.delete("t1")
    assert await world.sessions.get("t1") is None


async def test_deleting_a_user_removes_its_sessions(world: AuthWorld) -> None:
    user = await world.users.add("alice", "h", Role.ADMIN, T0)
    await world.sessions.create(make_session(user.id))
    await world.users.delete(user.id)
    assert await world.sessions.get("t1") is None


async def test_delete_for_user_and_purge_expired(world: AuthWorld) -> None:
    a = await world.users.add("a", "h", Role.ADMIN, T0)
    b = await world.users.add("b", "h", Role.ADMIN, T0)
    await world.sessions.create(make_session(a.id, "a1"))
    await world.sessions.create(make_session(a.id, "a2"))
    await world.sessions.create(make_session(b.id, "b-old", ttl_minutes=1))
    await world.sessions.create(make_session(b.id, "b-new", ttl_minutes=500))
    await world.sessions.delete_for_user(a.id)
    assert await world.sessions.get("a1") is None and await world.sessions.get("a2") is None
    assert await world.sessions.purge_expired(T0 + timedelta(minutes=10)) == 1
    assert await world.sessions.get("b-old") is None
    assert await world.sessions.get("b-new") is not None


async def test_throttle_locks_after_max_failures_and_resets(world: AuthWorld) -> None:
    t = world.throttle
    for _ in range(2):
        await t.record_failure("alice", T0, max_failures=3, lock_seconds=60)
    assert await t.retry_after("alice", T0) == 0
    await t.record_failure("alice", T0, max_failures=3, lock_seconds=60)
    assert await t.retry_after("alice", T0) == 60
    assert await t.retry_after("alice", T0 + timedelta(seconds=61)) == 0
    assert await t.retry_after("bob", T0) == 0
    await t.reset("alice")
    await t.record_failure("alice", T0, max_failures=3, lock_seconds=60)
    assert await t.retry_after("alice", T0) == 0


async def test_throttle_counter_restarts_after_the_lock_expired(world: AuthWorld) -> None:
    t = world.throttle
    for _ in range(3):
        await t.record_failure("alice", T0, max_failures=3, lock_seconds=60)
    later = T0 + timedelta(seconds=120)
    await t.record_failure("alice", later, max_failures=3, lock_seconds=60)
    assert await t.retry_after("alice", later) == 0  # 1 failure, not 4


def test_migration_creates_auth_tables(conn: sqlite3.Connection) -> None:
    tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"admin_sessions", "login_attempts"} <= tables
