"""Shared builders for the REST adapter tests (no network: every call goes through respx)."""

from typing import Any

import httpx

from conector_odoo.domain.errors import ResourceNotFound
from conector_odoo.domain.profiles import AuthMethod, ConnectionProfile, ProfileType, Secrets
from conector_odoo.domain.records import RecordFilter
from conector_odoo.domain.resources import EndpointSpec, PaginationConfig, ResourceConfig
from conector_odoo.infrastructure.rest.auth import build_authenticator
from conector_odoo.infrastructure.rest.endpoint import RestRecordEndpoint
from conector_odoo.infrastructure.rest.http import RestHttpClient

BASE = "https://api.test"
TOKEN = "tok-secret-value-123"


class FakeTime:
    """Deterministic clock whose ``sleep`` advances time instead of waiting."""

    def __init__(self) -> None:
        self.now = 1000.0
        self.sleeps: list[float] = []

    def clock(self) -> float:
        return self.now

    async def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds


def profile(**overrides: Any) -> ConnectionProfile:
    values: dict[str, Any] = {
        "id": None,
        "name": "p",
        "type": ProfileType.REST,
        "base_url": BASE,
        "auth_method": AuthMethod.BEARER,
        "timeout_seconds": 2.0,
    }
    values.update(overrides)
    return ConnectionProfile(**values)


def http_client(
    prof: ConnectionProfile | None = None,
    secrets: Secrets | None = None,
    fake: FakeTime | None = None,
    **options: Any,
) -> RestHttpClient:
    prof = prof or profile()
    secrets = secrets or Secrets(token=TOKEN)
    fake = fake or FakeTime()
    auth = build_authenticator(prof, secrets, clock=fake.clock)
    options.setdefault("clock", fake.clock)
    options.setdefault("sleep", fake.sleep)
    return RestHttpClient(
        prof.base_url,
        auth,
        extra_headers=prof.extra_headers,
        tls_verify=prof.tls_verify,
        timeout=prof.timeout_seconds,
        **options,
    )


def config(**overrides: Any) -> ResourceConfig:
    values: dict[str, Any] = {
        "name": "items",
        "label": "Items",
        "list_endpoint": EndpointSpec("GET", "/items"),
        "get_endpoint": EndpointSpec("GET", "/items/{id}"),
        "create_endpoint": EndpointSpec("POST", "/items"),
        "update_endpoint": EndpointSpec("PATCH", "/items/{id}"),
        "items_path": "items",
        "pagination": PaginationConfig(),
    }
    values.update(overrides)
    return ResourceConfig(**values)


class StaticConfigs:
    def __init__(self, *configs: ResourceConfig) -> None:
        self._by_name = {c.name: c for c in configs}

    async def get(self, resource: str) -> ResourceConfig:
        try:
            return self._by_name[resource]
        except KeyError:
            raise ResourceNotFound(f"unknown resource {resource}") from None


def endpoint(cfg: ResourceConfig | None = None, **client_options: Any) -> RestRecordEndpoint:
    return RestRecordEndpoint(http_client(**client_options), StaticConfigs(cfg or config()))


def query(request: httpx.Request) -> dict[str, str]:
    return dict(request.url.params)


async def collect(
    source: Any,
    resource: str = "items",
    size: int = 2,
    *,
    record_filter: RecordFilter | None = None,
) -> list[Any]:
    record_filter = record_filter or RecordFilter()
    return [
        record
        async for batch in source.iter_batches(resource, record_filter, size)
        for record in batch
    ]
