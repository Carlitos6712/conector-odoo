"""Builds record endpoints for connection profiles.

One class serves two needs:

* ``build_rest`` / ``build_odoo``: a fresh endpoint the caller owns and must ``aclose()``
  (previews, discovery);
* ``__call__(profile_id)``: the sync runner's ``EndpointFactory``. Endpoints are cached per
  profile so connection pools and OAuth tokens are reused across runs. The cache key includes the
  profile's ``updated_at``, so editing a profile makes the next run build a fresh endpoint; the
  replaced one is kept until ``aclose()`` because a run may still be using it.

Secrets are decrypted here, handed to the adapter and dropped. A vault problem surfaces as
``RemoteUnavailable`` (its message never contains secret material) so the run fails cleanly.
"""

import asyncio
import logging
from datetime import datetime

from conector_odoo.application.resources import CatalogResourceConfigProvider
from conector_odoo.config import Settings
from conector_odoo.domain.errors import ProfileNotFound, RemoteUnavailable, VaultError
from conector_odoo.domain.ports import (
    ConnectionProfileRepository,
    RecordEndpoint,
    ResourceCatalogRepository,
    ResourceConfigProvider,
    SecretVault,
)
from conector_odoo.domain.profiles import ConnectionProfile, ProfileType, Secrets
from conector_odoo.infrastructure.odoo.factory import build_odoo_endpoint
from conector_odoo.infrastructure.odoo.records import OdooRecordEndpoint
from conector_odoo.infrastructure.rest.endpoint import RestRecordEndpoint
from conector_odoo.infrastructure.rest.factory import build_rest_endpoint

logger = logging.getLogger(__name__)

_CacheKey = tuple[int, datetime | None]


class ProfileEndpoints:
    def __init__(
        self,
        profiles: ConnectionProfileRepository,
        catalog: ResourceCatalogRepository,
        vault: SecretVault,
        settings: Settings,
    ) -> None:
        self._profiles = profiles
        self._catalog = catalog
        self._vault = vault
        self._settings = settings
        self._cache: dict[_CacheKey, RecordEndpoint] = {}
        self._lock = asyncio.Lock()

    def build_rest(
        self, profile: ConnectionProfile, secrets: Secrets, configs: ResourceConfigProvider
    ) -> RestRecordEndpoint:
        return build_rest_endpoint(profile, secrets, configs)

    def build_odoo(self, profile: ConnectionProfile, secrets: Secrets) -> OdooRecordEndpoint:
        return build_odoo_endpoint(
            profile,
            secrets,
            protocol=self._settings.odoo_protocol,
            max_retries=self._settings.odoo_max_retries,
            max_concurrency=self._settings.odoo_max_concurrency,
        )

    async def __call__(self, profile_id: int) -> RecordEndpoint:
        stored = await self._profiles.get(profile_id)
        if stored is None:
            raise ProfileNotFound(f"connection profile {profile_id} not found")
        key = (profile_id, stored.profile.updated_at)
        async with self._lock:
            cached = self._cache.get(key)
            if cached is not None:
                return cached
            try:
                blob = stored.secrets_blob
                secrets = self._vault.decrypt(blob) if blob else Secrets()
            except VaultError as exc:
                raise RemoteUnavailable(
                    f"cannot load the credentials of the profile: {exc}"
                ) from None
            profile = stored.profile
            endpoint: RecordEndpoint
            if profile.type is ProfileType.REST:
                provider = CatalogResourceConfigProvider(self._catalog, profile_id)
                endpoint = self.build_rest(profile, secrets, provider)
            else:
                endpoint = self.build_odoo(profile, secrets)
            self._cache[key] = endpoint
            return endpoint

    async def aclose(self) -> None:
        """Close every endpoint handed out; one failing close never prevents the others."""
        async with self._lock:
            endpoints, self._cache = list(self._cache.values()), {}
        for endpoint in endpoints:
            try:
                await endpoint.aclose()  # type: ignore[attr-defined]
            except Exception:
                logger.exception("closing a profile endpoint failed")
