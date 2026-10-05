from datetime import timedelta

import pytest

from conector_odoo.application.auth import AuthConfig, AuthService
from conector_odoo.domain.auth import Role
from conector_odoo.domain.errors import (
    AdminUserInvalid,
    AdminUsernameTaken,
    AuthenticationFailed,
    LastAdminError,
    LoginLocked,
    SessionInvalid,
)
from tests.auth.helpers import PASSWORD, AuthWorld


async def seed(world: AuthWorld, username: str = "alice", role: Role = Role.ADMIN) -> int:
    return (await world.admin.create(username, PASSWORD, role)).id


async def test_login_issues_a_session_that_authenticates(world: AuthWorld) -> None:
    await seed(world)
    result = await world.auth.login("alice", PASSWORD)
    assert result.user.username == "alice" and result.csrf_token and result.token
    current = await world.auth.authenticate(result.token)
    assert current.user.id == result.user.id and current.csrf_token == result.csrf_token


async def test_token_is_not_stored_in_clear(world: AuthWorld, conn) -> None:  # type: ignore[no-untyped-def]
    await seed(world)
    result = await world.auth.login("alice", PASSWORD)
    stored = [r[0] for r in conn.execute("SELECT token_hash FROM admin_sessions")]
    assert stored and result.token not in stored


async def test_wrong_password_and_unknown_user_fail_identically(world: AuthWorld) -> None:
    await seed(world)
    with pytest.raises(AuthenticationFailed) as wrong:
        await world.auth.login("alice", "not the password!")
    with pytest.raises(AuthenticationFailed) as unknown:
        await world.auth.login("nobody", "not the password!")
    assert str(wrong.value) == str(unknown.value)


async def test_unknown_user_still_runs_a_password_verification(world: AuthWorld) -> None:
    calls: list[str] = []
    real = world.hasher.verify

    def spy(password_hash: str, password: str) -> bool:
        calls.append(password_hash)
        return real(password_hash, password)

    world.hasher.verify = spy  # type: ignore[method-assign]
    with pytest.raises(AuthenticationFailed):
        await world.auth.login("nobody", "whatever password")
    assert len(calls) == 1  # constant-time failure path: a dummy hash is verified


async def test_lockout_after_repeated_failures_even_with_the_right_password(
    world: AuthWorld,
) -> None:
    await seed(world)
    for _ in range(world.config.max_failures):
        with pytest.raises(AuthenticationFailed):
            await world.auth.login("alice", "bad password!!")
    with pytest.raises(LoginLocked) as locked:
        await world.auth.login("alice", PASSWORD)
    assert locked.value.retry_after_seconds > 0
    world.clock.advance(seconds=world.config.lockout_seconds + 1)
    assert (await world.auth.login("alice", PASSWORD)).user.username == "alice"


async def test_unknown_usernames_are_throttled_too(world: AuthWorld) -> None:
    for _ in range(world.config.max_failures):
        with pytest.raises(AuthenticationFailed):
            await world.auth.login("ghost", "bad password!!")
    with pytest.raises(LoginLocked):
        await world.auth.login("ghost", "bad password!!")


async def test_successful_login_resets_the_failure_counter(world: AuthWorld) -> None:
    await seed(world)
    for _ in range(world.config.max_failures - 1):
        with pytest.raises(AuthenticationFailed):
            await world.auth.login("alice", "bad password!!")
    await world.auth.login("alice", PASSWORD)
    with pytest.raises(AuthenticationFailed):  # one failure again, not locked
        await world.auth.login("alice", "bad password!!")


async def test_session_expires_absolutely(world: AuthWorld) -> None:
    await seed(world)
    result = await world.auth.login("alice", PASSWORD)
    world.clock.advance(seconds=world.config.session_ttl_seconds + 1)
    with pytest.raises(SessionInvalid):
        await world.auth.authenticate(result.token)


async def test_session_expires_when_idle_but_activity_extends_it(world: AuthWorld) -> None:
    await seed(world)
    result = await world.auth.login("alice", PASSWORD)
    step = world.config.idle_timeout_seconds - 60
    for _ in range(2):
        world.clock.advance(seconds=step)
        await world.auth.authenticate(result.token)
    world.clock.advance(seconds=world.config.idle_timeout_seconds + 1)
    with pytest.raises(SessionInvalid):
        await world.auth.authenticate(result.token)


async def test_login_rotates_the_session(world: AuthWorld) -> None:
    await seed(world)
    first = await world.auth.login("alice", PASSWORD)
    second = await world.auth.login("alice", PASSWORD, previous_token=first.token)
    assert second.token != first.token and second.csrf_token != first.csrf_token
    with pytest.raises(SessionInvalid):
        await world.auth.authenticate(first.token)
    await world.auth.authenticate(second.token)


async def test_logout_destroys_the_session(world: AuthWorld) -> None:
    await seed(world)
    result = await world.auth.login("alice", PASSWORD)
    await world.auth.logout(result.token)
    await world.auth.logout(result.token)  # idempotent
    with pytest.raises(SessionInvalid):
        await world.auth.authenticate(result.token)


async def test_garbage_tokens_are_invalid(world: AuthWorld) -> None:
    with pytest.raises(SessionInvalid):
        await world.auth.authenticate("nope")
    with pytest.raises(SessionInvalid):
        await world.auth.authenticate("")


async def test_deleted_user_loses_the_session(world: AuthWorld) -> None:
    await seed(world, "root")
    other = await seed(world, "bob", Role.OPERATOR)
    result = await world.auth.login("bob", PASSWORD)
    await world.admin.delete(other, acting_user_id=1)
    with pytest.raises(SessionInvalid):
        await world.auth.authenticate(result.token)


async def test_password_change_and_role_change_revoke_sessions(world: AuthWorld) -> None:
    await seed(world, "root")
    bob = await seed(world, "bob", Role.OPERATOR)
    first = await world.auth.login("bob", PASSWORD)
    await world.admin.update(bob, password="another long password")
    with pytest.raises(SessionInvalid):
        await world.auth.authenticate(first.token)
    second = await world.auth.login("bob", "another long password")
    await world.admin.update(bob, role=Role.ADMIN)
    with pytest.raises(SessionInvalid):
        await world.auth.authenticate(second.token)


async def test_bootstrap_creates_the_first_admin_only_when_no_users_exist(
    world: AuthWorld,
) -> None:
    assert await world.admin.bootstrap("first", PASSWORD) is True
    assert await world.admin.bootstrap("second", PASSWORD) is False
    users = await world.admin.list()
    assert [(u.username, u.role) for u in users] == [("first", Role.ADMIN)]


async def test_weak_password_and_duplicate_user_are_rejected(world: AuthWorld) -> None:
    with pytest.raises(AdminUserInvalid):
        await world.admin.create("alice", "short", Role.ADMIN)
    await seed(world)
    with pytest.raises(AdminUsernameTaken):
        await world.admin.create("ALICE", PASSWORD, Role.OPERATOR)


async def test_cannot_remove_or_demote_the_last_admin_or_delete_yourself(
    world: AuthWorld,
) -> None:
    only = await seed(world, "root")
    with pytest.raises(LastAdminError):
        await world.admin.update(only, role=Role.OPERATOR)
    with pytest.raises(LastAdminError):
        await world.admin.delete(only, acting_user_id=999)
    second = await seed(world, "second")
    with pytest.raises(AdminUserInvalid):  # deleting yourself is refused
        await world.admin.delete(second, acting_user_id=second)
    await world.admin.delete(second, acting_user_id=only)


def test_auth_config_defaults_are_sane() -> None:
    config = AuthConfig()
    assert config.idle_timeout_seconds < config.session_ttl_seconds
    assert config.max_failures >= 3 and config.lockout_seconds >= 60
    assert timedelta(seconds=config.session_ttl_seconds) <= timedelta(days=1)
    assert AuthService is not None
