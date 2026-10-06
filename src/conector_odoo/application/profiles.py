"""Use cases for connection profiles.

Read models (``ProfileView``) never carry secrets: they expose only ``has_secret`` flags, which are
derived from the secret *names* stored next to the profile, so listing needs no vault key.
"""

from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from datetime import datetime

from conector_odoo.application.active_odoo import OdooActivationLog
from conector_odoo.domain.errors import ProfileInUse, ProfileNotFound
from conector_odoo.domain.ports import (
    ConnectionProbe,
    ConnectionProfileRepository,
    SecretVault,
)
from conector_odoo.domain.profiles import (
    SECRET_FIELDS,
    AuthMethod,
    ConnectionProfile,
    ConnectionTestResult,
    ProbeStep,
    ProfileType,
    Secrets,
    StoredProfile,
)

_MIN_MASKED_LENGTH = 4  # shorter values would mangle ordinary text when masked


@dataclass(frozen=True, slots=True)
class ProfileView:
    id: int
    name: str
    type: ProfileType
    base_url: str
    auth_method: AuthMethod
    extra_headers: dict[str, str]
    tls_verify: bool
    timeout_seconds: float
    odoo_db: str | None
    odoo_login: str | None
    token_url: str | None
    username: str | None
    scope: str | None
    api_key_header: str
    has_secret: dict[str, bool] = field(default_factory=dict)
    created_at: datetime | None = None
    updated_at: datetime | None = None
    # Odoo profiles only: is this the live Odoo connection, and when did it last connect.
    is_active: bool = False
    last_connected_at: datetime | None = None


def to_view(profile: ConnectionProfile) -> ProfileView:
    assert profile.id is not None
    return ProfileView(
        id=profile.id,
        name=profile.name,
        type=profile.type,
        base_url=profile.base_url,
        auth_method=profile.auth_method,
        extra_headers=dict(profile.extra_headers),
        tls_verify=profile.tls_verify,
        timeout_seconds=profile.timeout_seconds,
        odoo_db=profile.odoo_db,
        odoo_login=profile.odoo_login,
        token_url=profile.token_url,
        username=profile.username,
        scope=profile.scope,
        api_key_header=profile.api_key_header,
        has_secret={name: name in profile.secret_fields for name in SECRET_FIELDS},
        created_at=profile.created_at,
        updated_at=profile.updated_at,
    )


async def _with_activity(views: list[ProfileView], log: OdooActivationLog | None) -> None:
    """Fill ``is_active`` / ``last_connected_at`` in place (no-op without an activation log)."""
    if log is None:
        return
    record = await log.load()
    for index, view in enumerate(views):
        if view.type is ProfileType.ODOO:
            views[index] = replace(
                view,
                is_active=record.active_profile_id == view.id,
                last_connected_at=record.per_profile.get(view.id),
            )


def _seal(vault: SecretVault, secrets: Secrets) -> tuple[bytes | None, frozenset[str]]:
    """Encrypt ``secrets`` (no key needed when there is nothing to store)."""
    present = secrets.present_fields()
    return (vault.encrypt(secrets) if present else None), present


class CreateProfile:
    def __init__(self, repo: ConnectionProfileRepository, vault: SecretVault) -> None:
        self._repo = repo
        self._vault = vault

    async def execute(
        self, draft: ConnectionProfile, secrets: Secrets | None = None
    ) -> ProfileView:
        """Raises ``ProfileNameTaken``; ``VaultNotConfigured`` when secrets need a missing key."""
        blob, present = _seal(self._vault, Secrets().merged(secrets or Secrets()))
        saved = await self._repo.add(replace(draft, id=None, secret_fields=present), blob)
        return to_view(saved)


class UpdateProfile:
    def __init__(
        self,
        repo: ConnectionProfileRepository,
        vault: SecretVault,
        log: OdooActivationLog | None = None,
    ) -> None:
        self._repo = repo
        self._vault = vault
        self._log = log

    async def execute(
        self, profile_id: int, draft: ConnectionProfile, secrets: Secrets | None = None
    ) -> ProfileView:
        """Replace the non-secret fields; in ``secrets`` ``None`` keeps, ``""`` clears a field.

        Raises ``ProfileNotFound`` / ``ProfileNameTaken``. The vault is only touched when some
        secret field is actually provided.
        """
        stored = await self._repo.get(profile_id)
        if stored is None:
            raise ProfileNotFound(f"connection profile {profile_id} not found")
        blob, present = stored.secrets_blob, stored.profile.secret_fields
        if secrets is not None and any(
            getattr(secrets, name) is not None for name in SECRET_FIELDS
        ):
            current = self._vault.decrypt(blob) if blob else Secrets()
            blob, present = _seal(self._vault, current.merged(secrets))
        saved = await self._repo.update(
            replace(
                draft,
                id=profile_id,
                secret_fields=present,
                created_at=stored.profile.created_at,
            ),
            blob,
        )
        views = [to_view(saved)]
        await _with_activity(views, self._log)
        return views[0]


class GetProfile:
    def __init__(
        self, repo: ConnectionProfileRepository, log: OdooActivationLog | None = None
    ) -> None:
        self._repo = repo
        self._log = log

    async def execute(self, profile_id: int) -> ProfileView:
        stored = await self._repo.get(profile_id)
        if stored is None:
            raise ProfileNotFound(f"connection profile {profile_id} not found")
        views = [to_view(stored.profile)]
        await _with_activity(views, self._log)
        return views[0]


class ListProfiles:
    def __init__(
        self, repo: ConnectionProfileRepository, log: OdooActivationLog | None = None
    ) -> None:
        self._repo = repo
        self._log = log

    async def execute(self) -> list[ProfileView]:
        views = [to_view(stored.profile) for stored in await self._repo.list()]
        await _with_activity(views, self._log)
        return views


class DeleteProfile:
    def __init__(
        self, repo: ConnectionProfileRepository, log: OdooActivationLog | None = None
    ) -> None:
        self._repo = repo
        self._log = log

    async def execute(self, profile_id: int) -> None:
        """Raises ``ProfileNotFound`` / ``ProfileInUse`` (also while it is the active Odoo one)."""
        if self._log is not None and (await self._log.load()).active_profile_id == profile_id:
            raise ProfileInUse(
                f"connection profile {profile_id} is the active Odoo connection; "
                "activate another profile or disconnect it first"
            )
        await self._repo.delete(profile_id)
        if self._log is not None:
            await self._log.forget_profile(profile_id)


class TestConnection:
    """Run the connection probe of the profile type, for a saved profile or an unsaved draft."""

    __test__ = False  # not a pytest test class despite the name

    def __init__(
        self,
        repo: ConnectionProfileRepository,
        vault: SecretVault,
        probes: Mapping[ProfileType, ConnectionProbe],
    ) -> None:
        self._repo = repo
        self._vault = vault
        self._probes = probes

    async def test_saved(self, profile_id: int) -> ConnectionTestResult:
        stored: StoredProfile | None = await self._repo.get(profile_id)
        if stored is None:
            raise ProfileNotFound(f"connection profile {profile_id} not found")
        blob = stored.secrets_blob
        secrets = self._vault.decrypt(blob) if blob else Secrets()
        return await self._run(stored.profile, secrets)

    async def test_draft(
        self, draft: ConnectionProfile, secrets: Secrets | None = None
    ) -> ConnectionTestResult:
        return await self._run(draft, secrets or Secrets())

    async def _run(self, profile: ConnectionProfile, secrets: Secrets) -> ConnectionTestResult:
        steps = await self._probes[profile.type].probe(profile, secrets)
        return ConnectionTestResult.from_steps([_masked(step, secrets) for step in steps])


def _masked(step: ProbeStep, secrets: Secrets) -> ProbeStep:
    """Defense in depth: a probe message that echoes a credential never leaves the use case."""
    values = [v for v in secrets.as_dict().values() if len(v) >= _MIN_MASKED_LENGTH]

    def mask(text: str | None) -> str | None:
        for value in values:
            text = None if text is None else text.replace(value, "***")
        return text

    return replace(step, detail=mask(step.detail) or "", hint=mask(step.hint))
