import sqlite3

import pytest

from conector_odoo.application.auth import AuthConfig
from conector_odoo.domain.errors import AuthenticationFailed, CurrentPasswordInvalid, LoginLocked
from tests.auth.helpers import PASSWORD, AuthWorld

BAD = "definitely not it"
IP_A = "203.0.113.10"
IP_B = "203.0.113.11"


def small_config(**overrides: int) -> AuthConfig:
    values = {"max_failures": 5, "ip_max_failures": 3, "ip_window_seconds": 600}
    values.update(overrides)
    return AuthConfig(**values)


@pytest.fixture
def ipworld(conn: sqlite3.Connection) -> AuthWorld:
    return AuthWorld(conn, small_config())


async def seed(world: AuthWorld, username: str = "alice") -> None:
    from conector_odoo.domain.auth import Role

    await world.admin.create(username, PASSWORD, Role.ADMIN)


async def fail(world: AuthWorld, username: str, ip: str, times: int = 1) -> None:
    for _ in range(times):
        with pytest.raises(AuthenticationFailed):
            await world.auth.login(username, BAD, client_ip=ip)


# -- repository ---------------------------------------------------------------------------------


async def test_ip_throttle_counts_a_sliding_window(ipworld: AuthWorld) -> None:
    t = ipworld.ip_throttle
    kw = {"max_failures": 3, "window_seconds": 600}
    for _ in range(2):
        await t.record_failure(IP_A, ipworld.clock(), window_seconds=600)
    assert await t.retry_after(IP_A, ipworld.clock(), **kw) == 0
    await t.record_failure(IP_A, ipworld.clock(), window_seconds=600)
    assert await t.retry_after(IP_A, ipworld.clock(), **kw) == 600
    ipworld.clock.advance(seconds=100)
    assert await t.retry_after(IP_A, ipworld.clock(), **kw) == 500
    assert await t.retry_after(IP_B, ipworld.clock(), **kw) == 0  # other IPs unaffected
    ipworld.clock.advance(seconds=501)
    assert await t.retry_after(IP_A, ipworld.clock(), **kw) == 0  # window expired


async def test_ip_throttle_window_slides_instead_of_resetting(ipworld: AuthWorld) -> None:
    t = ipworld.ip_throttle
    kw = {"max_failures": 3, "window_seconds": 600}
    await t.record_failure(IP_A, ipworld.clock(), window_seconds=600)  # t=0
    ipworld.clock.advance(seconds=400)
    await t.record_failure(IP_A, ipworld.clock(), window_seconds=600)  # t=400
    await t.record_failure(IP_A, ipworld.clock(), window_seconds=600)  # t=400
    assert await t.retry_after(IP_A, ipworld.clock(), **kw) == 200  # until the t=0 row ages out
    ipworld.clock.advance(seconds=201)
    assert await t.retry_after(IP_A, ipworld.clock(), **kw) == 0  # only 2 rows left in window


async def test_old_rows_are_purged_on_write(ipworld: AuthWorld, conn: sqlite3.Connection) -> None:
    t = ipworld.ip_throttle
    await t.record_failure(IP_A, ipworld.clock(), window_seconds=600)
    ipworld.clock.advance(seconds=601)
    await t.record_failure(IP_B, ipworld.clock(), window_seconds=600)
    rows = [r[0] for r in conn.execute("SELECT ip FROM login_ip_failures")]
    assert rows == [IP_B]


async def test_known_ips_expire_and_are_per_username(ipworld: AuthWorld) -> None:
    k = ipworld.known_ips
    await k.remember("alice", IP_A, ipworld.clock(), max_age_seconds=1000)
    assert await k.is_known("alice", IP_A, ipworld.clock(), max_age_seconds=1000)
    assert not await k.is_known("alice", IP_B, ipworld.clock(), max_age_seconds=1000)
    assert not await k.is_known("bob", IP_A, ipworld.clock(), max_age_seconds=1000)
    ipworld.clock.advance(seconds=1001)
    assert not await k.is_known("alice", IP_A, ipworld.clock(), max_age_seconds=1000)


# -- service ------------------------------------------------------------------------------------


async def test_ip_is_throttled_after_max_failures_across_many_usernames(
    ipworld: AuthWorld,
) -> None:
    await seed(ipworld)
    for name in ("u1", "u2", "u3"):  # password spraying: one failure per username
        await fail(ipworld, name, IP_A)
    with pytest.raises(LoginLocked) as locked:
        await ipworld.auth.login("u4", BAD, client_ip=IP_A)
    assert locked.value.retry_after_seconds == 600
    # even the right credentials of a real user are refused from the throttled IP
    with pytest.raises(LoginLocked):
        await ipworld.auth.login("alice", PASSWORD, client_ip=IP_A)
    # another IP is unaffected
    assert (await ipworld.auth.login("alice", PASSWORD, client_ip=IP_B)).user.username == "alice"


async def test_ip_throttle_expires_with_an_injected_clock(ipworld: AuthWorld) -> None:
    await seed(ipworld)
    await fail(ipworld, "alice", IP_A, times=3)
    with pytest.raises(LoginLocked):
        await ipworld.auth.login("alice", PASSWORD, client_ip=IP_A)
    ipworld.clock.advance(seconds=601)
    assert (await ipworld.auth.login("alice", PASSWORD, client_ip=IP_A)).user.username == "alice"


async def test_throttled_ip_does_not_add_rows_while_blocked(
    ipworld: AuthWorld, conn: sqlite3.Connection
) -> None:
    await fail(ipworld, "ghost", IP_A, times=3)
    for _ in range(5):
        with pytest.raises(LoginLocked):
            await ipworld.auth.login("ghost", BAD, client_ip=IP_A)
    assert conn.execute("SELECT COUNT(*) FROM login_ip_failures").fetchone()[0] == 3


async def test_ip_throttle_does_not_enumerate_users(ipworld: AuthWorld) -> None:
    await seed(ipworld)
    await fail(ipworld, "alice", IP_A, times=3)
    with pytest.raises(LoginLocked) as real:
        await ipworld.auth.login("alice", BAD, client_ip=IP_A)
    with pytest.raises(LoginLocked) as ghost:
        await ipworld.auth.login("ghost", BAD, client_ip=IP_A)
    assert str(real.value) == str(ghost.value)
    assert real.value.retry_after_seconds == ghost.value.retry_after_seconds


async def test_success_does_not_clear_the_ip_counter(ipworld: AuthWorld) -> None:
    # An attacker owning one valid account must not be able to wipe the IP counter by logging in.
    await seed(ipworld)
    await fail(ipworld, "ghost", IP_A, times=2)
    await ipworld.auth.login("alice", PASSWORD, client_ip=IP_A)
    await fail(ipworld, "ghost", IP_A, times=1)
    with pytest.raises(LoginLocked):
        await ipworld.auth.login("alice", PASSWORD, client_ip=IP_A)


async def test_success_resets_only_the_username_counter(ipworld: AuthWorld) -> None:
    await seed(ipworld)
    await fail(ipworld, "alice", IP_A, times=2)
    await ipworld.auth.login("alice", PASSWORD, client_ip=IP_B)  # right password elsewhere
    assert await ipworld.throttle.retry_after("alice", ipworld.clock()) == 0
    # IP_A's two failures are still counted: one more reaches the limit of 3
    await fail(ipworld, "ghost", IP_A, times=1)
    with pytest.raises(LoginLocked):
        await ipworld.auth.login("ghost", BAD, client_ip=IP_A)


async def test_password_change_failures_count_against_the_ip(ipworld: AuthWorld) -> None:
    await seed(ipworld)
    user = (await ipworld.auth.login("alice", PASSWORD, client_ip=IP_B)).user
    for _ in range(3):
        with pytest.raises(CurrentPasswordInvalid):
            await ipworld.auth.change_password(user, BAD, "a brand new password", client_ip=IP_A)
    with pytest.raises(LoginLocked):
        await ipworld.auth.change_password(user, PASSWORD, "a brand new password", client_ip=IP_A)


# -- username lockout vs. other IPs -------------------------------------------------------------


async def test_known_ip_bypasses_a_username_lockout_caused_by_other_ips(
    conn: sqlite3.Connection,
) -> None:
    world = AuthWorld(conn, small_config(ip_max_failures=50))
    await seed(world)
    await world.auth.login("alice", PASSWORD, client_ip=IP_A)  # IP_A becomes known for alice
    for i in range(5):  # attacker locks the account from other addresses
        await fail(world, "alice", f"198.51.100.{i}")
    with pytest.raises(LoginLocked):  # a stranger with the right password is still locked out
        await world.auth.login("alice", PASSWORD, client_ip=IP_B)
    assert (await world.auth.login("alice", PASSWORD, client_ip=IP_A)).user.username == "alice"
    assert await world.throttle.retry_after("alice", world.clock()) == 0  # success cleared it


async def test_known_ip_with_the_wrong_password_is_still_a_failure(
    conn: sqlite3.Connection,
) -> None:
    world = AuthWorld(conn, small_config(ip_max_failures=50))
    await seed(world)
    await world.auth.login("alice", PASSWORD, client_ip=IP_A)
    for i in range(5):
        await fail(world, "alice", f"198.51.100.{i}")
    await fail(world, "alice", IP_A)  # verified and refused, not skipped
    with pytest.raises(LoginLocked):
        await world.auth.login("alice", PASSWORD, client_ip=IP_B)


async def test_known_ip_bypass_can_be_disabled(conn: sqlite3.Connection) -> None:
    world = AuthWorld(conn, small_config(ip_max_failures=50, known_ip_seconds=0))
    await seed(world)
    await world.auth.login("alice", PASSWORD, client_ip=IP_A)
    for i in range(5):
        await fail(world, "alice", f"198.51.100.{i}")
    with pytest.raises(LoginLocked):
        await world.auth.login("alice", PASSWORD, client_ip=IP_A)


async def test_known_ip_is_not_recorded_for_failed_logins(conn: sqlite3.Connection) -> None:
    world = AuthWorld(conn, small_config(ip_max_failures=50))
    await seed(world)
    await fail(world, "alice", IP_A)
    assert not await world.known_ips.is_known("alice", IP_A, world.clock(), max_age_seconds=10**6)
