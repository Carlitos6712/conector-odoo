import sqlite3
from datetime import UTC, datetime, timedelta

from conector_odoo.application.auth import AuthConfig, AuthService, UserAdmin
from conector_odoo.infrastructure.auth.hasher import Argon2PasswordHasher
from conector_odoo.infrastructure.auth.repository import (
    SqliteAdminUserRepository,
    SqliteIpLoginThrottle,
    SqliteKnownLoginIps,
    SqliteLoginThrottle,
    SqliteSessionStore,
)

T0 = datetime(2026, 5, 1, 12, 0, tzinfo=UTC)
PASSWORD = "correct horse battery"


class FakeClock:
    def __init__(self) -> None:
        self.now = T0

    def __call__(self) -> datetime:
        return self.now

    def advance(self, **kwargs: float) -> None:
        self.now += timedelta(**kwargs)


def fast_hasher() -> Argon2PasswordHasher:
    return Argon2PasswordHasher(time_cost=1, memory_cost=8, parallelism=1)


class AuthWorld:
    def __init__(self, conn: sqlite3.Connection, config: AuthConfig | None = None) -> None:
        self.clock = FakeClock()
        self.users = SqliteAdminUserRepository(conn)
        self.sessions = SqliteSessionStore(conn)
        self.throttle = SqliteLoginThrottle(conn)
        self.ip_throttle = SqliteIpLoginThrottle(conn)
        self.known_ips = SqliteKnownLoginIps(conn)
        self.hasher = fast_hasher()
        self.config = config or AuthConfig()
        self.auth = AuthService(
            self.users,
            self.sessions,
            self.throttle,
            self.hasher,
            self.clock,
            self.config,
            ip_throttle=self.ip_throttle,
            known_ips=self.known_ips,
        )
        self.admin = UserAdmin(self.users, self.sessions, self.hasher, self.clock)
