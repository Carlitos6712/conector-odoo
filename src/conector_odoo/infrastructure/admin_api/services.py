"""Composition of the admin side: repositories and use cases over the admin database."""

import logging
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime

from conector_odoo.application.auth import AuthConfig, AuthService, UserAdmin
from conector_odoo.application.profiles import (
    CreateProfile,
    DeleteProfile,
    GetProfile,
    ListProfiles,
    TestConnection,
    UpdateProfile,
)
from conector_odoo.application.resources import (
    DeleteResource,
    DiscoverResources,
    GetResource,
    ListResources,
    PreviewResource,
    SaveResource,
)
from conector_odoo.config import Settings
from conector_odoo.domain.ports import ConnectionProbe
from conector_odoo.domain.profiles import ProfileType
from conector_odoo.infrastructure.auth.hasher import Argon2PasswordHasher
from conector_odoo.infrastructure.auth.repository import (
    SqliteAdminUserRepository,
    SqliteLoginThrottle,
    SqliteSessionStore,
)
from conector_odoo.infrastructure.endpoints import ProfileEndpoints
from conector_odoo.infrastructure.openapi.importer import OpenApiImporter
from conector_odoo.infrastructure.profiles.odoo_probe import OdooConnectionProbe
from conector_odoo.infrastructure.profiles.repository import SqliteConnectionProfileRepository
from conector_odoo.infrastructure.profiles.rest_probe import RestConnectionProbe
from conector_odoo.infrastructure.profiles.vault import FernetVault
from conector_odoo.infrastructure.resources.repository import SqliteResourceCatalogRepository

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ProfileServices:
    create: CreateProfile
    update: UpdateProfile
    get: GetProfile
    list: ListProfiles
    delete: DeleteProfile
    test: TestConnection
    probes: dict[ProfileType, ConnectionProbe]  # mutable on purpose: tests swap probes


@dataclass(frozen=True)
class ResourceServices:
    save: SaveResource
    list: ListResources
    get: GetResource
    delete: DeleteResource
    preview: PreviewResource
    discover: DiscoverResources
    importer: OpenApiImporter


@dataclass(frozen=True)
class AdminServices:
    auth: AuthService
    users: UserAdmin
    endpoints: ProfileEndpoints
    profiles: ProfileServices
    resources: ResourceServices


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
    profile_repo = SqliteConnectionProfileRepository(conn)
    catalog = SqliteResourceCatalogRepository(conn)
    key = settings.encryption_key.get_secret_value() if settings.encryption_key else None
    vault = FernetVault(key)
    endpoints = ProfileEndpoints(profile_repo, catalog, vault, settings)
    probes: dict[ProfileType, ConnectionProbe] = {
        ProfileType.REST: RestConnectionProbe(),
        ProfileType.ODOO: OdooConnectionProbe(),
    }
    # The builders are looked up at call time so tests (and later customisation) can swap them.
    return AdminServices(
        auth=AuthService(users, sessions, SqliteLoginThrottle(conn), hasher, _now, config),
        users=UserAdmin(users, sessions, hasher, _now),
        endpoints=endpoints,
        profiles=ProfileServices(
            create=CreateProfile(profile_repo, vault),
            update=UpdateProfile(profile_repo, vault),
            get=GetProfile(profile_repo),
            list=ListProfiles(profile_repo),
            delete=DeleteProfile(profile_repo),
            test=TestConnection(profile_repo, vault, probes),
            probes=probes,
        ),
        resources=ResourceServices(
            save=SaveResource(profile_repo, catalog),
            list=ListResources(profile_repo, catalog),
            get=GetResource(catalog),
            delete=DeleteResource(catalog),
            preview=PreviewResource(
                profile_repo,
                catalog,
                vault,
                lambda profile, secrets, configs: endpoints.build_rest(profile, secrets, configs),
                lambda profile, secrets: endpoints.build_odoo(profile, secrets),
            ),
            discover=DiscoverResources(
                profile_repo,
                catalog,
                vault,
                lambda profile, secrets: endpoints.build_odoo(profile, secrets),
            ),
            importer=OpenApiImporter(),
        ),
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
