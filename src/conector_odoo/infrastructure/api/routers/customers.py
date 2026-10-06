from typing import Annotated

from fastapi import APIRouter, Depends, Path, Query, Request, Response
from fastapi.responses import StreamingResponse

from conector_odoo.application.customers import (
    BulkUpsertCustomers,
    CreateCustomer,
    ExportCustomers,
    GetCustomer,
    SearchCustomers,
    UpdateCustomer,
)
from conector_odoo.application.pagination import MAX_BATCH_SIZE, MAX_PAGE_SIZE
from conector_odoo.config import Settings
from conector_odoo.domain.entities import CustomerFilter, CustomerQuery
from conector_odoo.domain.errors import OdooValidationError
from conector_odoo.infrastructure.api.dependencies import (
    get_bulk_upsert_customers,
    get_create_customer,
    get_export_customers,
    get_get_customer,
    get_search_customers,
    get_settings,
    get_update_customer,
)
from conector_odoo.infrastructure.api.errors import scrub
from conector_odoo.infrastructure.api.idempotency import IDEMPOTENCY_RESPONSES, GuardDep
from conector_odoo.infrastructure.api.ndjson import ndjson_response
from conector_odoo.infrastructure.api.schemas import (
    BulkCustomersIn,
    BulkCustomersOut,
    BulkItemResultOut,
    CustomerCreate,
    CustomerOut,
    CustomerPatch,
    ErrorOut,
)
from conector_odoo.infrastructure.api.security import require_api_key

router = APIRouter(
    prefix="/customers",
    tags=["customers"],
    dependencies=[Depends(require_api_key)],
    responses={401: {"model": ErrorOut}},
)

CustomerId = Annotated[int, Path(gt=0)]


@router.post("", status_code=201, response_model=CustomerOut, responses=IDEMPOTENCY_RESPONSES)
async def create_customer(
    body: CustomerCreate,
    use_case: Annotated[CreateCustomer, Depends(get_create_customer)],
    guard: GuardDep,
) -> Response:
    async def action() -> CustomerOut:
        return CustomerOut.from_domain(await use_case.execute(body.to_domain()))

    return await guard.run(body, action, 201)


@router.get("", response_model=list[CustomerOut])
async def search_customers(
    use_case: Annotated[SearchCustomers, Depends(get_search_customers)],
    email: str | None = None,
    name: str | None = None,
    limit: Annotated[int, Query(ge=1, le=MAX_PAGE_SIZE)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[CustomerOut]:
    query = CustomerQuery(email=email, name=name, limit=limit, offset=offset)
    return [CustomerOut.from_domain(c) for c in await use_case.execute(query)]


@router.get(
    "/export",
    response_class=StreamingResponse,
    responses={
        200: {
            "content": {"application/x-ndjson": {}},
            "description": (
                "One CustomerOut JSON object per line. If the export fails after streaming "
                'started, the last line is {"error": ..., "detail": ...}.'
            ),
        }
    },
)
async def export_customers(
    request: Request,
    use_case: Annotated[ExportCustomers, Depends(get_export_customers)],
    email: str | None = None,
    name: str | None = None,
    active: bool | None = None,
    batch_size: Annotated[int | None, Query(ge=1, le=MAX_BATCH_SIZE)] = None,
) -> StreamingResponse:
    # Declared before ``/{customer_id}`` so "export" is never parsed as an id.
    batches = use_case.execute(CustomerFilter(email=email, name=name, active=active), batch_size)
    return await ndjson_response(batches, CustomerOut.from_domain, request, "customers.ndjson")


@router.post(
    "/bulk",
    status_code=200,
    response_model=BulkCustomersOut,
    responses=IDEMPOTENCY_RESPONSES,
)
async def bulk_upsert_customers(
    body: BulkCustomersIn,
    use_case: Annotated[BulkUpsertCustomers, Depends(get_bulk_upsert_customers)],
    settings: Annotated[Settings, Depends(get_settings)],
    guard: GuardDep,
) -> Response:
    """Create or update many customers matched by email; per-item results, never a partial 500."""
    if len(body.items) > settings.bulk_max_items:
        # Checked before anything runs: no lookups, no writes, no idempotency key claimed.
        raise OdooValidationError(f"items: at most {settings.bulk_max_items} items per request")

    async def action() -> BulkCustomersOut:
        result = await use_case.execute(body.to_domain(), body.match_by)
        return BulkCustomersOut(
            created=result.created,
            updated=result.updated,
            failed=result.failed,
            results=[
                BulkItemResultOut(
                    index=item.index,
                    status=item.status,
                    id=item.id,
                    error=scrub(item.error, settings) if item.error is not None else None,
                )
                for item in result.results
            ],
        )

    return await guard.run(body, action, 200)


@router.get("/{customer_id}", response_model=CustomerOut, responses={404: {"model": ErrorOut}})
async def get_customer(
    customer_id: CustomerId, use_case: Annotated[GetCustomer, Depends(get_get_customer)]
) -> CustomerOut:
    return CustomerOut.from_domain(await use_case.execute(customer_id))


@router.patch("/{customer_id}", response_model=CustomerOut, responses={404: {"model": ErrorOut}})
async def update_customer(
    customer_id: CustomerId,
    body: CustomerPatch,
    use_case: Annotated[UpdateCustomer, Depends(get_update_customer)],
) -> CustomerOut:
    return CustomerOut.from_domain(await use_case.execute(customer_id, body.to_domain()))
