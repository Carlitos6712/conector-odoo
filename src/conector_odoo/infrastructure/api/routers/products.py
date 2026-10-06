from typing import Annotated

from fastapi import APIRouter, Depends, Path, Query, Request
from fastapi.responses import StreamingResponse

from conector_odoo.application.pagination import MAX_BATCH_SIZE, MAX_PAGE_SIZE
from conector_odoo.application.products import ExportProducts, GetProduct, ListProducts
from conector_odoo.infrastructure.api.dependencies import (
    get_export_products,
    get_get_product,
    get_list_products,
)
from conector_odoo.infrastructure.api.ndjson import ndjson_response
from conector_odoo.infrastructure.api.schemas import ErrorOut, ProductOut
from conector_odoo.infrastructure.api.security import require_api_key

router = APIRouter(
    prefix="/products",
    tags=["products"],
    dependencies=[Depends(require_api_key)],
    responses={401: {"model": ErrorOut}},
)


@router.get("", response_model=list[ProductOut])
async def list_products(
    use_case: Annotated[ListProducts, Depends(get_list_products)],
    limit: Annotated[int, Query(ge=1, le=MAX_PAGE_SIZE)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[ProductOut]:
    return [ProductOut.from_domain(p) for p in await use_case.execute(limit, offset)]


@router.get(
    "/export",
    response_class=StreamingResponse,
    responses={
        200: {
            "content": {"application/x-ndjson": {}},
            "description": (
                "One ProductOut JSON object per line. If the export fails after streaming "
                'started, the last line is {"error": ..., "detail": ...}.'
            ),
        }
    },
)
async def export_products(
    request: Request,
    use_case: Annotated[ExportProducts, Depends(get_export_products)],
    batch_size: Annotated[int | None, Query(ge=1, le=MAX_BATCH_SIZE)] = None,
) -> StreamingResponse:
    # Declared before ``/{product_id}`` so "export" is never parsed as an id.
    batches = use_case.execute(batch_size)
    return await ndjson_response(batches, ProductOut.from_domain, request, "products.ndjson")


@router.get("/{product_id}", response_model=ProductOut, responses={404: {"model": ErrorOut}})
async def get_product(
    product_id: Annotated[int, Path(gt=0)],
    use_case: Annotated[GetProduct, Depends(get_get_product)],
) -> ProductOut:
    return ProductOut.from_domain(await use_case.execute(product_id))
