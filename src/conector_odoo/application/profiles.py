"""Use cases for connection profiles.

Read models (``ProfileView``) never carry secrets: they expose only ``has_secret`` flags, which are
derived from the secret *names* stored next to the profile, so listing needs no vault key.
"""

from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from datetime import datetime

from conector_odoo.domain.errors import ProfileNotFound
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
    ProfileType,
    Secrets,
    StoredProfile,
)


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
    scope: str | None
    api_key_header: str
    has_secret: dict[str, bool] = field(default_factory=dict)
    created_at: datetime | None = None
    updated_at: datetime | None = None


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
        scope=profile.scope,
        api_key_header=profile.api_key_header,
        has_secret={name: name in profile.secret_fields for name in SECRET_FIELDS},
        created_at=profile.created_at,
        updated_at=profile.updated_at,
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
    def __init__(self, repo: ConnectionProfileRepository, vault: SecretVault) -> None:
        self._repo = repo
        self._vault = vault

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
        return to_view(saved)


class GetProfile:
    def __init__(self, repo: ConnectionProfileRepository) -> None:
        self._repo = repo

    async def execute(self, profile_id: int) -> ProfileView:
        stored = await self._repo.get(profile_id)
        if stored is None:
            raise ProfileNotFound(f"connection profile {profile_id} not found")
        return to_view(stored.profile)


class ListProfiles:
    def __init__(self, repo: ConnectionProfileRepository) -> None:
        self._repo = repo

    async def execute(self) -> list[ProfileView]:
        return [to_view(stored.profile) for stored in await self._repo.list()]


class DeleteProfile:
    def __init__(self, repo: ConnectionProfileRepository) -> None:
        self._repo = repo

    async def execute(self, profile_id: int) -> None:
        """Raises ``ProfileNotFound`` / ``ProfileInUse``."""
        await self._repo.delete(profile_id)


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
        return ConnectionTestResult.from_steps(steps)
