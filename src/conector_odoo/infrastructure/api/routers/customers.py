from typing import Annotated

from fastapi import APIRouter, Depends, Path, Query, Response

from conector_odoo.application.customers import (
    CreateCustomer,
    GetCustomer,
    SearchCustomers,
    UpdateCustomer,
)
from conector_odoo.application.pagination import MAX_PAGE_SIZE
from conector_odoo.domain.entities import CustomerQuery
from conector_odoo.infrastructure.api.dependencies import (
    get_create_customer,
    get_get_customer,
    get_search_customers,
    get_update_customer,
)
from conector_odoo.infrastructure.api.idempotency import IDEMPOTENCY_RESPONSES, GuardDep
from conector_odoo.infrastructure.api.schemas import (
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
