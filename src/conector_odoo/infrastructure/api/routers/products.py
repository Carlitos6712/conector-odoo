from typing import Annotated

from fastapi import APIRouter, Depends, Path, Query

from conector_odoo.application.products import GetProduct, ListProducts
from conector_odoo.infrastructure.api.dependencies import get_get_product, get_list_products
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
    limit: Annotated[int, Query(ge=1, le=1000)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[ProductOut]:
    return [ProductOut.from_domain(p) for p in await use_case.execute(limit, offset)]


@router.get("/{product_id}", response_model=ProductOut, responses={404: {"model": ErrorOut}})
async def get_product(
    product_id: Annotated[int, Path(gt=0)],
    use_case: Annotated[GetProduct, Depends(get_get_product)],
) -> ProductOut:
    return ProductOut.from_domain(await use_case.execute(product_id))
