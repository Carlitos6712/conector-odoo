"""``/admin/api/mappings``: versioned mappings, dry-run and suggestions.

Dry-run and suggestions read live data from the remote systems, so they are POSTs (admin only).
"""

from fastapi import APIRouter, Query, Response

from conector_odoo.application.mappings import DryRunMapping, SaveMapping, suggest_mapping
from conector_odoo.domain.errors import MappingInvalid
from conector_odoo.domain.mapping_codec import mapping_from_dict
from conector_odoo.infrastructure.admin_api.deps import AdminDep
from conector_odoo.infrastructure.admin_api.mapping_support import sample_provider, schema_resolver
from conector_odoo.infrastructure.admin_api.schemas.mappings import (
    DryRunIn,
    DryRunOut,
    MappingPutIn,
    MappingSaveOut,
    StoredMappingListOut,
    StoredMappingOut,
    SuggestIn,
    SuggestOut,
)

router = APIRouter(prefix="/mappings", tags=["admin-mappings"])


@router.get("")
async def list_mappings(admin: AdminDep) -> StoredMappingListOut:
    stored = await admin.mappings.list.execute()
    return StoredMappingListOut(items=[StoredMappingOut.of(m) for m in stored])


@router.post("/dry-run")
async def dry_run(body: DryRunIn, admin: AdminDep) -> DryRunOut:
    """Map a sample of the source without writing anything (a draft or a saved mapping)."""
    use_case = DryRunMapping(
        admin.mappings.repo,
        schema_resolver(
            admin.endpoints, body.source_profile_id, body.target_profile_id, tolerant=False
        ),
        sample_provider(admin.endpoints, body.source_profile_id),
    )
    if body.definition is not None:
        report = await use_case.execute(mapping_from_dict(body.definition), body.limit)
    else:
        assert body.name is not None
        report = await use_case.execute_saved(body.name, body.version, body.limit)
    return DryRunOut.of(report)


@router.post("/suggest")
async def suggest(body: SuggestIn, admin: AdminDep) -> SuggestOut:
    """Draft ``direct`` rules for source/target fields whose names match."""
    source = await (await admin.endpoints(body.source_profile_id)).describe(body.source_resource)
    target = await (await admin.endpoints(body.target_profile_id)).describe(body.target_resource)
    return SuggestOut.of(suggest_mapping(source, target))


@router.get("/{name}")
async def get_mapping(
    name: str, admin: AdminDep, version: int | None = Query(default=None, ge=1)
) -> StoredMappingOut:
    return StoredMappingOut.of(await admin.mappings.get.execute(name, version))


@router.get("/{name}/versions")
async def list_versions(name: str, admin: AdminDep) -> StoredMappingListOut:
    stored = await admin.mappings.versions.execute(name)
    return StoredMappingListOut(items=[StoredMappingOut.of(m) for m in stored])


@router.put("/{name}")
async def put_mapping(name: str, body: MappingPutIn, admin: AdminDep) -> MappingSaveOut:
    """Validate and store ``definition`` as the next version (nothing is stored when it equals
    the latest one)."""
    definition = mapping_from_dict(body.definition)
    if definition.name != name:
        raise MappingInvalid("name: the mapping name in the body must match the URL")
    resolver = schema_resolver(
        admin.endpoints, body.source_profile_id, body.target_profile_id, tolerant=True
    )
    result = await SaveMapping(admin.mappings.repo, resolver).execute(definition)
    return MappingSaveOut.of(result)


@router.delete("/{name}", status_code=204)
async def delete_mapping(name: str, admin: AdminDep) -> Response:
    await admin.mappings.delete.execute(name)
    return Response(status_code=204)
