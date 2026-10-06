"""The Odoo connection the connector is using, and how to change it at runtime.

``ActiveOdooConnection`` resolves the connection at startup (active profile > legacy env > none),
and activates/clears a profile later: the candidate client is built first, the profile is probed
BEFORE anything changes, the choice is persisted, and only then is the live connection swapped.
Any failure before the swap leaves the previous connection untouched.
"""

import asyncio
import logging
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime

from conector_odoo.config import Settings
from conector_odoo.domain.active_odoo import OdooSource
from conector_odoo.domain.errors import (
    OdooActivationFailed,
    ProfileNotFound,
    ProfileValidationError,
)
from conector_odoo.domain.ports import (
    AppSettingsRepository,
    ConnectionProbe,
    ConnectionProfileRepository,
    OdooRuntime,
    PreparedOdooConnection,
    SecretVault,
)
from conector_odoo.domain.profiles import ConnectionTestResult, ProfileType, Secrets

logger = logging.getLogger(__name__)

PREFIX = "odoo."
_ACTIVE = "odoo.active_profile_id"
_LAST_AT = "odoo.last_connected_at"
_LAST_PROFILE = "odoo.last_connected_profile_id"
_PER_PROFILE = "odoo.profile."
_PER_PROFILE_SUFFIX = ".last_connected_at"


def _now() -> datetime:
    return datetime.now(UTC)


def _parse_int(raw: str | None) -> int | None:
    try:
        return None if raw is None else int(raw)
    except ValueError:
        return None


def _parse_time(raw: str | None) -> datetime | None:
    try:
        return None if raw is None else datetime.fromisoformat(raw)
    except ValueError:
        return None


@dataclass(frozen=True, slots=True)
class ActivationRecord:
    """What is persisted about the Odoo connection."""

    active_profile_id: int | None = None
    last_connected_at: datetime | None = None
    last_connected_profile_id: int | None = None
    per_profile: Mapping[int, datetime] = field(default_factory=dict)


class OdooActivationLog:
    """Typed view over the ``odoo.*`` entries of the app settings store."""

    def __init__(self, store: AppSettingsRepository, clock: Callable[[], datetime] = _now) -> None:
        self._store = store
        self._clock = clock

    async def load(self) -> ActivationRecord:
        raw = await self._store.get_all(PREFIX)
        per_profile: dict[int, datetime] = {}
        for key, value in raw.items():
            if key.startswith(_PER_PROFILE) and key.endswith(_PER_PROFILE_SUFFIX):
                profile_id = _parse_int(key[len(_PER_PROFILE) : -len(_PER_PROFILE_SUFFIX)])
                moment = _parse_time(value)
                if profile_id is not None and moment is not None:
                    per_profile[profile_id] = moment
        return ActivationRecord(
            active_profile_id=_parse_int(raw.get(_ACTIVE)),
            last_connected_at=_parse_time(raw.get(_LAST_AT)),
            last_connected_profile_id=_parse_int(raw.get(_LAST_PROFILE)),
            per_profile=per_profile,
        )

    async def record_activation(self, profile_id: int) -> None:
        moment = self._clock().isoformat()
        await self._store.set_many(
            {
                _ACTIVE: str(profile_id),
                _LAST_AT: moment,
                _LAST_PROFILE: str(profile_id),
                f"{_PER_PROFILE}{profile_id}{_PER_PROFILE_SUFFIX}": moment,
            }
        )

    async def clear_active(self) -> None:
        await self._store.delete(_ACTIVE)

    async def forget_profile(self, profile_id: int) -> None:
        await self._store.delete(f"{_PER_PROFILE}{profile_id}{_PER_PROFILE_SUFFIX}")


@dataclass(frozen=True, slots=True)
class ActiveOdooStatus:
    """What the admin UI shows; never carries a secret."""

    source: OdooSource
    profile_id: int | None
    profile_name: str | None
    base_url: str | None
    db: str | None
    login: str | None
    last_connected_at: datetime | None
    # ``active`` (a connection is live), ``not_configured`` or ``fallback`` (the stored active
    # profile could not be loaded at startup, so another source is being used).
    status: str
    warning: str | None = None


class ActiveOdooConnection:
    def __init__(
        self,
        profiles: ConnectionProfileRepository,
        vault: SecretVault,
        probes: Mapping[ProfileType, ConnectionProbe],
        runtime: OdooRuntime,
        log: OdooActivationLog,
        settings: Settings,
    ) -> None:
        self._profiles = profiles
        self._vault = vault
        self._probes = probes  # looked up per call: tests swap probes
        self._runtime = runtime
        self._log = log
        self._settings = settings
        self._lock = asyncio.Lock()
        self._warning: str | None = None

    # -- startup -----------------------------------------------------------------------------

    async def restore(self) -> None:
        """Resolve the connection at startup. Never raises: problems become a warning."""
        async with self._lock:
            self._warning = None
            record = await self._log.load()
            if record.active_profile_id is not None:
                try:
                    prepared = await self._prepare_stored_profile(record.active_profile_id)
                    await self._runtime.commit(prepared)
                    return
                except Exception as exc:
                    self._warning = (
                        f"the active Odoo profile {record.active_profile_id} could not be "
                        f"loaded ({_reason(exc)}); using the "
                        f"{'environment' if self._settings.odoo_env_configured() else 'no'} "
                        "connection instead"
                    )
                    logger.warning(self._warning)
            await self._install_env_or_none()
            if self._settings.odoo_env_partial() and not self._settings.odoo_env_configured():
                logger.warning(
                    "ODOO_URL, ODOO_DB, ODOO_USER and ODOO_API_KEY must ALL be set to use the "
                    "environment connection; ignoring the partial configuration"
                )

    async def _prepare_stored_profile(self, profile_id: int) -> PreparedOdooConnection:
        stored = await self._profiles.get(profile_id)
        if stored is None:
            raise ProfileNotFound(f"connection profile {profile_id} not found")
        if stored.profile.type is not ProfileType.ODOO:
            raise ProfileValidationError("only an odoo connection profile can be the active one")
        blob = stored.secrets_blob
        secrets = self._vault.decrypt(blob) if blob else Secrets()
        return self._runtime.prepare_profile(stored.profile, secrets)

    async def _install_env_or_none(self) -> None:
        await self._runtime.commit(self._runtime.prepare_env())

    # -- use cases ---------------------------------------------------------------------------

    async def activate(self, profile_id: int) -> ActiveOdooStatus:
        """Probe the profile and, only if it works, make it the live connection.

        Raises ``ProfileNotFound``, ``ProfileValidationError`` (not an Odoo profile),
        ``Vault*`` errors and ``OdooActivationFailed`` (probe failed; nothing changed).
        """
        async with self._lock:
            stored = await self._profiles.get(profile_id)
            if stored is None:
                raise ProfileNotFound(f"connection profile {profile_id} not found")
            profile = stored.profile
            if profile.type is not ProfileType.ODOO:
                raise ProfileValidationError(
                    "only an odoo connection profile can be the active one"
                )
            blob = stored.secrets_blob
            secrets = self._vault.decrypt(blob) if blob else Secrets()
            prepared = self._runtime.prepare_profile(profile, secrets)  # built first, no I/O
            try:
                steps = await self._probes[ProfileType.ODOO].probe(profile, secrets)
                result = ConnectionTestResult.from_steps(steps)
                if not result.ok:
                    raise _failure(result, secrets)
                await self._log.record_activation(profile_id)
            except BaseException:
                await self._runtime.discard(prepared)
                raise
            await self._runtime.commit(prepared)
            self._warning = None
        return await self.status()

    async def refresh_if_active(self, profile_id: int) -> None:
        """Rebuild the live client after the ACTIVE profile was edited (new URL, key, ...).

        No probe: the operator may be mid-edit and the old client keeps serving until the swap.
        A profile that is not the active one is ignored; a failure keeps the old connection and
        is logged, never raised (the edit itself already succeeded).
        """
        async with self._lock:
            if (await self._log.load()).active_profile_id != profile_id:
                return
            try:
                prepared = await self._prepare_stored_profile(profile_id)
            except Exception as exc:
                logger.warning(
                    "the edited active Odoo profile %s could not be reloaded (%s); "
                    "the previous connection stays in use",
                    profile_id,
                    _reason(exc),
                )
                return
            await self._runtime.commit(prepared)

    async def clear(self) -> ActiveOdooStatus:
        """Forget the active profile; fall back to the env connection when complete, else none."""
        async with self._lock:
            await self._log.clear_active()
            self._warning = None
            await self._install_env_or_none()
        return await self.status()

    async def status(self) -> ActiveOdooStatus:
        record = await self._log.load()
        current = self._runtime.current
        last_at = record.last_connected_at
        if current is None:
            return ActiveOdooStatus(
                source=OdooSource.NONE,
                profile_id=None,
                profile_name=None,
                base_url=None,
                db=None,
                login=None,
                last_connected_at=last_at,
                status="not_configured",
                warning=self._warning,
            )
        profile_id = current.profile_id
        if current.source is OdooSource.PROFILE and profile_id is not None:
            last_at = record.per_profile.get(profile_id, last_at)
        return ActiveOdooStatus(
            source=current.source,
            profile_id=profile_id,
            profile_name=current.profile_name,
            base_url=current.base_url,
            db=current.db,
            login=current.login,
            last_connected_at=last_at,
            status="fallback" if self._warning else "active",
            warning=self._warning,
        )


def _reason(exc: Exception) -> str:
    # Only the error class and its message; domain errors never carry secret material.
    return f"{type(exc).__name__}: {exc}"


def _failure(result: ConnectionTestResult, secrets: Secrets) -> OdooActivationFailed:
    failed = next(step for step in result.steps if not step.ok)
    detail = failed.detail
    for value in secrets.as_dict().values():
        if len(value) >= 4:
            detail = detail.replace(value, "***")
    message = f"the connection test failed at step '{failed.name}': {detail.rstrip('.')}."
    if failed.hint:
        message = f"{message} {failed.hint}"
    return OdooActivationFailed(
        message,
        failed_step=failed.name,
        steps=tuple((s.name, s.ok, s.detail, s.hint) for s in result.steps),
    )
