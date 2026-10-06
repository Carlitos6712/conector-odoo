"""``/admin/api/profiles/{id}/resources``: the REST resource catalog, previews, OpenAPI import and
discovery. Anything that contacts the remote system (preview, import, discover) is a POST, hence
admin only."""

from fastapi import APIRouter, Query, Response

from conector_odoo.domain.errors import ResourceConfigInvalid
from conector_odoo.infrastructure.admin_api.deps import AdminDep
from conector_odoo.infrastructure.admin_api.schemas.resources import (
    DiscoveredListOut,
    ImportReportOut,
    OpenApiImportIn,
    PreviewOut,
    ResourcePutIn,
    StoredResourceListOut,
    StoredResourceOut,
)

router = APIRouter(prefix="/profiles/{profile_id}", tags=["admin-resources"])


@router.get("/resources")
async def list_resources(profile_id: int, admin: AdminDep) -> StoredResourceListOut:
    return StoredResourceListOut.of(await admin.resources.list.report(profile_id))


# Fixed paths first: "import" must not be read as a resource name.
@router.post("/resources/import")
async def import_openapi(
    profile_id: int, body: OpenApiImportIn, admin: AdminDep
) -> ImportReportOut:
    """Turn an OpenAPI/Swagger document into resource candidates. Nothing is saved."""
    await admin.profiles.get.execute(profile_id)  # 404 for an unknown profile
    importer = admin.resources.importer
    if body.document is not None:
        report = importer.parse(body.document, base_path=body.base_path)
    else:
        assert body.url is not None
        report = await importer.import_url(body.url, base_path=body.base_path)
    return ImportReportOut.of(report)


@router.get("/resources/{name}")
async def get_resource(profile_id: int, name: str, admin: AdminDep) -> StoredResourceOut:
    return StoredResourceOut.of(await admin.resources.get.execute(profile_id, name))


@router.put("/resources/{name}")
async def put_resource(
    profile_id: int, name: str, body: ResourcePutIn, admin: AdminDep
) -> StoredResourceOut:
    """Create or replace a catalog entry."""
    if body.name != name:
        raise ResourceConfigInvalid("the resource name in the body must match the URL")
    stored = await admin.resources.save.execute(profile_id, body.to_domain(), body.source)
    return StoredResourceOut.of(stored)


@router.delete("/resources/{name}", status_code=204)
async def delete_resource(profile_id: int, name: str, admin: AdminDep) -> Response:
    await admin.resources.delete.execute(profile_id, name)
    return Response(status_code=204)


@router.post("/resources/{name}/preview")
async def preview_resource(
    profile_id: int, name: str, admin: AdminDep, limit: int = Query(default=5, ge=1, le=20)
) -> PreviewOut:
    """A few live records plus the schema. For Odoo profiles ``name`` is the model."""
    return PreviewOut.of(await admin.resources.preview.execute(profile_id, name, limit))


@router.post("/discover")
async def discover(profile_id: int, admin: AdminDep) -> DiscoveredListOut:
    """Odoo: every model (``ir.model``); REST: the catalog."""
    return DiscoveredListOut.of(await admin.resources.discover.execute(profile_id))
