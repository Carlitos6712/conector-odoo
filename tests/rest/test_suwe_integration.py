"""Optional check against the local SUWE fake API; skipped when it is not running."""

import httpx
import pytest

from conector_odoo.domain.profiles import AuthMethod, Secrets
from conector_odoo.domain.records import RecordFilter
from conector_odoo.domain.resources import (
    EndpointSpec,
    PaginationConfig,
    PaginationStrategy,
)
from conector_odoo.infrastructure.rest.factory import build_rest_endpoint
from tests.rest.helpers import StaticConfigs, config, profile

HEALTH = "http://localhost:8000/api/v1/healthy"


def _fake_is_up() -> bool:
    try:
        return httpx.get(HEALTH, timeout=1.0).status_code == 200
    except httpx.HTTPError:
        return False


pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(not _fake_is_up(), reason="SUWE fake API is not reachable on :8000"),
]


async def test_lists_every_suwe_client_with_page_pagination() -> None:
    cfg = config(
        name="clients",
        label="Clients",
        list_endpoint=EndpointSpec("GET", "/organization/clients"),
        get_endpoint=EndpointSpec("GET", "/organization/clients/{id}"),
        items_path="items",
        id_field="uuid",
        pagination=PaginationConfig(
            strategy=PaginationStrategy.PAGE,
            page_param="page",
            size_param="page_size",
            total_pages_path="total_pages",
        ),
    )
    prof = profile(
        base_url="http://localhost:8000/api/v1", auth_method=AuthMethod.BEARER, timeout_seconds=10
    )
    endpoint = build_rest_endpoint(prof, Secrets(token="dummy"), StaticConfigs(cfg))
    try:
        records = [
            r async for batch in endpoint.iter_batches("clients", RecordFilter(), 10) for r in batch
        ]
        assert len(records) == 37
        assert len({r.id for r in records}) == 37
        assert await endpoint.get("clients", records[0].id or "") is not None
    finally:
        await endpoint.aclose()
