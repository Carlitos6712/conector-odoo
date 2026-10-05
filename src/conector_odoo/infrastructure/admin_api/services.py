"""Composition of the admin side: repositories and use cases over the admin database."""

import logging
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime

from conector_odoo.application.auth import AuthConfig, AuthService, UserAdmin
from conector_odoo.config import Settings
from conector_odoo.infrastructure.auth.hasher import Argon2PasswordHasher
from conector_odoo.infrastructure.auth.repository import (
    SqliteAdminUserRepository,
    SqliteLoginThrottle,
    SqliteSessionStore,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class AdminServices:
    auth: AuthService
    users: UserAdmin


def _now() -> datetime:
    return datetime.now(UTC)


def build_admin_services(settings: Settings, conn: sqlite3.Connection) -> AdminServices:
    hasher = Argon2PasswordHasher(
        time_cost=settings.admin_argon2_time_cost,
        memory_cost=settings.admin_argon2_memory_kib,
        parallelism=settings.admin_argon2_parallelism,
    )
    users = SqliteAdminUserRepository(conn)
    sessions = SqliteSessionStore(conn)
    config = AuthConfig(
        session_ttl_seconds=settings.admin_session_ttl_seconds,
        idle_timeout_seconds=settings.admin_session_idle_seconds,
        max_failures=settings.admin_login_max_failures,
        lockout_seconds=settings.admin_login_lockout_seconds,
    )
    return AdminServices(
        auth=AuthService(users, sessions, SqliteLoginThrottle(conn), hasher, _now, config),
        users=UserAdmin(users, sessions, hasher, _now),
    )


async def bootstrap_first_admin(settings: Settings, services: AdminServices) -> None:
    """Create the configured first admin, only when no admin user exists at all."""
    if settings.admin_bootstrap_user is None or settings.admin_bootstrap_password is None:
        return
    created = await services.users.bootstrap(
        settings.admin_bootstrap_user, settings.admin_bootstrap_password.get_secret_value()
    )
    if created:
        logger.info("bootstrapped the first admin user", extra={"username": "<configured>"})
