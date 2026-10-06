"""Glue between the mapping use cases and live endpoints.

The mapping use cases take injected schema/sample callables; here they are backed by the profile
endpoint factory, scoped to the profile ids a request names.
"""

from conector_odoo.application.mappings import SampleProvider, SchemaResolver
from conector_odoo.domain.errors import RemoteAuthError, RemoteUnavailable, ResourceNotFound
from conector_odoo.domain.mapping import MappingDefinition
from conector_odoo.domain.records import Record, ResourceSchema
from conector_odoo.infrastructure.endpoints import ProfileEndpoints


async def _describe(
    endpoints: ProfileEndpoints, profile_id: int | None, resource: str, *, tolerant: bool
) -> ResourceSchema | None:
    if profile_id is None:
        return None
    try:
        endpoint = await endpoints(profile_id)
        return await endpoint.describe(resource)
    except ResourceNotFound:
        return None
    except (RemoteAuthError, RemoteUnavailable):
        if tolerant:
            return None  # saving a mapping must not depend on the remote being up
        raise


def schema_resolver(
    endpoints: ProfileEndpoints,
    source_profile_id: int | None,
    target_profile_id: int | None,
    *,
    tolerant: bool,
) -> SchemaResolver:
    """``tolerant``: an unreachable profile yields ``None`` (skip the check) instead of an error."""

    async def resolve(
        definition: MappingDefinition,
    ) -> tuple[ResourceSchema | None, ResourceSchema | None]:
        return (
            await _describe(
                endpoints, source_profile_id, definition.source_resource, tolerant=tolerant
            ),
            await _describe(
                endpoints, target_profile_id, definition.target_resource, tolerant=tolerant
            ),
        )

    return resolve


def sample_provider(endpoints: ProfileEndpoints, source_profile_id: int) -> SampleProvider:
    async def sample(definition: MappingDefinition, limit: int) -> list[Record]:
        endpoint = await endpoints(source_profile_id)
        return await endpoint.sample(definition.source_resource, limit)

    return sample
