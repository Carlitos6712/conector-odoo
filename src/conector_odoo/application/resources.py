"""Use cases for the resource catalog: save/list/get/delete, live preview and discovery.

Secrets are decrypted only inside ``PreviewResource`` / ``DiscoverResources``, handed to the
endpoint factory and dropped; results carry records and schemas, never credentials.
"""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol

from conector_odoo.domain.errors import (
    CatalogResourceNotFound,
    ProfileNotFound,
    ProfileValidationError,
    ResourceNotFound,
)
from conector_odoo.domain.ports import (
    ConnectionProfileRepository,
    RecordSource,
    ResourceCatalogRepository,
    ResourceConfigProvider,
    SecretVault,
)
from conector_odoo.domain.profiles import ConnectionProfile, ProfileType, Secrets
from conector_odoo.domain.records import Record, RecordFilter, ResourceSchema
from conector_odoo.domain.resource_codec import validate_resource_config
from conector_odoo.domain.resources import ResourceConfig, ResourceSource, StoredResource

PREVIEW_MAX_LIMIT = 20
_DISCOVERY_BATCH = 500


class ClosableSource(RecordSource, Protocol):
    async def aclose(self) -> None: ...


RestEndpointFactory = Callable[[ConnectionProfile, Secrets, ResourceConfigProvider], ClosableSource]
OdooEndpointFactory = Callable[[ConnectionProfile, Secrets], ClosableSource]


@dataclass(frozen=True, slots=True)
class PreviewResult:
    records: tuple[Record, ...]
    schema: ResourceSchema


@dataclass(frozen=True, slots=True)
class DiscoveredResource:
    name: str
    label: str


class CatalogResourceConfigProvider:
    """``ResourceConfigProvider`` backed by the catalog of one profile."""

    def __init__(self, catalog: ResourceCatalogRepository, profile_id: int) -> None:
        self._catalog = catalog
        self._profile_id = profile_id

    async def get(self, resource: str) -> ResourceConfig:
        stored = await self._catalog.get(self._profile_id, resource)
        if stored is None:
            raise ResourceNotFound(f"resource {resource!r} is not in the catalog")
        return stored.config


async def _profile(profiles: ConnectionProfileRepository, profile_id: int) -> ConnectionProfile:
    stored = await profiles.get(profile_id)
    if stored is None:
        raise ProfileNotFound(f"connection profile {profile_id} not found")
    return stored.profile


async def _secrets(
    profiles: ConnectionProfileRepository, vault: SecretVault, profile_id: int
) -> tuple[ConnectionProfile, Secrets]:
    stored = await profiles.get(profile_id)
    if stored is None:
        raise ProfileNotFound(f"connection profile {profile_id} not found")
    blob = stored.secrets_blob
    return stored.profile, (vault.decrypt(blob) if blob else Secrets())


class SaveResource:
    def __init__(
        self, profiles: ConnectionProfileRepository, catalog: ResourceCatalogRepository
    ) -> None:
        self._profiles = profiles
        self._catalog = catalog

    async def execute(
        self,
        profile_id: int,
        config: ResourceConfig,
        source: ResourceSource = ResourceSource.MANUAL,
    ) -> StoredResource:
        """Create or replace ``config`` by name.

        Raises ``ProfileNotFound``, ``ProfileValidationError`` (not a REST profile) and
        ``ResourceConfigInvalid``.
        """
        profile = await _profile(self._profiles, profile_id)
        if profile.type is not ProfileType.REST:
            raise ProfileValidationError(
                "the resource catalog is for REST profiles; Odoo models are discovered"
            )
        validate_resource_config(config)
        return await self._catalog.save(profile_id, config, source)


class ListResources:
    def __init__(
        self, profiles: ConnectionProfileRepository, catalog: ResourceCatalogRepository
    ) -> None:
        self._profiles = profiles
        self._catalog = catalog

    async def execute(self, profile_id: int) -> list[StoredResource]:
        await _profile(self._profiles, profile_id)
        return await self._catalog.list(profile_id)


class GetResource:
    def __init__(self, catalog: ResourceCatalogRepository) -> None:
        self._catalog = catalog

    async def execute(self, profile_id: int, name: str) -> StoredResource:
        stored = await self._catalog.get(profile_id, name)
        if stored is None:
            raise CatalogResourceNotFound(f"resource {name!r} not found in profile {profile_id}")
        return stored


class DeleteResource:
    def __init__(self, catalog: ResourceCatalogRepository) -> None:
        self._catalog = catalog

    async def execute(self, profile_id: int, name: str) -> None:
        await self._catalog.delete(profile_id, name)


class PreviewResource:
    """Fetch a few live records plus the schema. REST resources must be in the catalog; for an
    Odoo profile ``resource`` is the model name."""

    def __init__(
        self,
        profiles: ConnectionProfileRepository,
        catalog: ResourceCatalogRepository,
        vault: SecretVault,
        build_rest: RestEndpointFactory,
        build_odoo: OdooEndpointFactory,
    ) -> None:
        self._profiles = profiles
        self._catalog = catalog
        self._vault = vault
        self._build_rest = build_rest
        self._build_odoo = build_odoo

    async def execute(self, profile_id: int, resource: str, limit: int = 5) -> PreviewResult:
        """``limit`` is clamped to ``1..PREVIEW_MAX_LIMIT``. Remote failures propagate as the
        adapters' domain errors."""
        limit = max(1, min(limit, PREVIEW_MAX_LIMIT))
        profile, secrets = await _secrets(self._profiles, self._vault, profile_id)
        if profile.type is ProfileType.REST:
            if await self._catalog.get(profile_id, resource) is None:
                raise CatalogResourceNotFound(f"resource {resource!r} not found in profile")
            provider = CatalogResourceConfigProvider(self._catalog, profile_id)
            endpoint = self._build_rest(profile, secrets, provider)
        else:
            endpoint = self._build_odoo(profile, secrets)
        try:
            records = await endpoint.sample(resource, limit)
            schema = await endpoint.describe(resource)
        finally:
            await endpoint.aclose()
        return PreviewResult(tuple(records[:limit]), schema)


class DiscoverResources:
    """Odoo: every non-transient model (``ir.model``); REST: the catalog."""

    def __init__(
        self,
        profiles: ConnectionProfileRepository,
        catalog: ResourceCatalogRepository,
        vault: SecretVault,
        build_odoo: OdooEndpointFactory,
    ) -> None:
        self._profiles = profiles
        self._catalog = catalog
        self._vault = vault
        self._build_odoo = build_odoo

    async def execute(self, profile_id: int) -> list[DiscoveredResource]:
        profile, secrets = await _secrets(self._profiles, self._vault, profile_id)
        if profile.type is ProfileType.REST:
            return [
                DiscoveredResource(r.config.name, r.config.label)
                for r in await self._catalog.list(profile_id)
            ]
        endpoint = self._build_odoo(profile, secrets)
        flt = RecordFilter(raw={"domain": [["transient", "=", False]]})
        found: list[DiscoveredResource] = []
        try:
            async for batch in endpoint.iter_batches("ir.model", flt, _DISCOVERY_BATCH):
                found.extend(
                    DiscoveredResource(str(r.get("model")), str(r.get("name") or r.get("model")))
                    for r in batch
                    if r.get("model")
                )
        finally:
            await endpoint.aclose()
        return sorted(found, key=lambda d: d.name)
