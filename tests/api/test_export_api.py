import json

import pytest

from conector_odoo.domain.entities import CustomerData, CustomerFilter, Product
from conector_odoo.domain.errors import OdooPermissionError, OdooUnavailable
from tests.api.conftest import API_KEY, ODOO_KEY, Env


def lines(text: str) -> list[dict[str, object]]:
    return [json.loads(line) for line in text.splitlines()]


async def seed(env: Env, count: int) -> None:
    for i in range(1, count + 1):
        await env.customers.create(
            CustomerData(name=f"Cust {i}", email=f"c{i}@x.io", country_code="ES")
        )


async def test_customers_export_streams_every_row_as_ndjson(env: Env) -> None:
    await seed(env, 5)
    response = env.client.get("/customers/export?batch_size=2")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/x-ndjson")
    assert response.headers["content-disposition"] == 'attachment; filename="customers.ndjson"'
    rows = lines(response.text)
    assert [r["id"] for r in rows] == [1, 2, 3, 4, 5]
    assert rows[0] == {
        "id": 1,
        "name": "Cust 1",
        "email": "c1@x.io",
        "phone": None,
        "street": None,
        "city": None,
        "zip": None,
        "country_code": "ES",
        "vat": None,
        "is_company": False,
        "active": True,
    }
    assert response.text.endswith("\n")
    assert env.customers.export_calls == [(CustomerFilter(), 2)]


async def test_customers_export_passes_filters_down(env: Env) -> None:
    await seed(env, 3)
    response = env.client.get("/customers/export?email=c2@x.io&name=Cust&active=true")
    assert [r["id"] for r in lines(response.text)] == [2]
    assert env.customers.export_calls == [
        (CustomerFilter(email="c2@x.io", name="Cust", active=True), None)
    ]


def test_customers_export_empty_is_an_empty_200_body(env: Env) -> None:
    response = env.client.get("/customers/export")
    assert response.status_code == 200
    assert response.text == ""
    assert response.headers["content-type"].startswith("application/x-ndjson")


def test_export_route_is_not_captured_by_the_id_route(env: Env) -> None:
    response = env.client.get("/customers/export")
    assert response.status_code == 200  # not 422 from /customers/{customer_id}
    assert env.client.get("/customers/abc").status_code == 422


@pytest.mark.parametrize("size", ["0", "-1", "5001", "abc"])
@pytest.mark.parametrize("path", ["/customers/export", "/products/export"])
def test_export_validates_batch_size(env: Env, path: str, size: str) -> None:
    response = env.client.get(f"{path}?batch_size={size}")
    assert response.status_code == 422
    assert response.json()["error"] == "validation_error"


@pytest.mark.parametrize("size", ["1", "5000"])
def test_export_accepts_the_batch_size_bounds(env: Env, size: str) -> None:
    assert env.client.get(f"/customers/export?batch_size={size}").status_code == 200
    assert env.client.get(f"/products/export?batch_size={size}").status_code == 200


@pytest.mark.parametrize("path", ["/customers/export", "/products/export"])
def test_export_requires_the_api_key(secured_env: Env, path: str) -> None:
    assert secured_env.client.get(path).status_code == 401
    assert secured_env.client.get(path, headers={"X-API-Key": "wrong"}).status_code == 401
    assert secured_env.client.get(path, headers={"X-API-Key": API_KEY}).status_code == 200


def test_products_export_streams_ndjson(env: Env) -> None:
    env.products.items[4] = Product(id=4, name="P4", list_price=9.5, uom_name="Units")
    response = env.client.get("/products/export?batch_size=3")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/x-ndjson")
    assert response.headers["content-disposition"] == 'attachment; filename="products.ndjson"'
    rows = lines(response.text)
    assert [r["id"] for r in rows] == [1, 2, 3, 4]
    assert rows[3] == {
        "id": 4,
        "name": "P4",
        "default_code": None,
        "list_price": 9.5,
        "uom_name": "Units",
        "active": True,
    }
    assert env.products.export_calls == [3]


async def test_error_before_the_first_byte_uses_the_normal_error_mapping(env: Env) -> None:
    await seed(env, 3)
    env.customers.export_error = OdooPermissionError("no access")
    env.customers.export_error_after = 0
    response = env.client.get("/customers/export")
    assert response.status_code == 403
    assert response.json() == {"error": "permission_denied", "detail": "no access"}


async def test_mid_stream_failure_appends_a_scrubbed_error_line(
    env: Env, caplog: pytest.LogCaptureFixture
) -> None:
    await seed(env, 5)
    env.customers.export_error = OdooUnavailable(f"cannot reach Odoo {ODOO_KEY}")
    env.customers.export_error_after = 1
    with caplog.at_level("WARNING"):
        response = env.client.get("/customers/export?batch_size=2")
    assert response.status_code == 200  # the status was already sent
    rows = lines(response.text)
    assert [r.get("id") for r in rows[:2]] == [1, 2]
    assert rows[-1] == {"error": "odoo_unavailable", "detail": "cannot reach Odoo ***"}
    assert len(rows) == 3
    assert ODOO_KEY not in response.text
    assert "export failed mid-stream" in caplog.text
    assert ODOO_KEY not in caplog.text


async def test_unexpected_mid_stream_failure_hides_the_details(env: Env) -> None:
    await seed(env, 4)
    env.customers.export_error = RuntimeError("secret internals")
    response = env.client.get("/customers/export?batch_size=2")
    rows = lines(response.text)
    assert rows[-1]["error"] == "internal_error"
    assert "secret internals" not in response.text


def test_products_export_mid_stream_failure_appends_error_line(env: Env) -> None:
    env.products.export_error = OdooUnavailable("down")
    env.products.export_error_after = 1
    response = env.client.get("/products/export?batch_size=2")
    rows = lines(response.text)
    assert [r.get("id") for r in rows[:2]] == [1, 2]
    assert rows[-1] == {"error": "odoo_unavailable", "detail": "down"}


async def test_stream_pulls_batches_lazily_and_closes_the_source() -> None:
    from collections.abc import AsyncIterator
    from typing import Any, cast

    from conector_odoo.infrastructure.api.ndjson import ndjson_response
    from conector_odoo.infrastructure.api.schemas import ProductOut

    pulled = 0
    closed = False

    async def source() -> AsyncIterator[list[Product]]:
        nonlocal pulled, closed
        try:
            for start in range(0, 10, 2):
                pulled += 1
                yield [Product(id=start + 1, name="a"), Product(id=start + 2, name="b")]
        finally:
            closed = True

    response = await ndjson_response(
        source(), ProductOut.from_domain, cast(Any, None), "products.ndjson"
    )
    assert pulled == 1  # only the first batch, to detect early errors
    body = response.body_iterator
    chunks = [await anext(body), await anext(body)]
    assert pulled == 2  # still one batch at a time
    assert chunks[0].count(b"\n") == 2  # type: ignore[union-attr]
    async for _ in body:
        pass
    assert pulled == 5
    assert closed
