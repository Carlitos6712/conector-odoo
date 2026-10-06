import sqlite3
from collections.abc import Iterator
from dataclasses import replace
from typing import Any

import pytest
from cryptography.fernet import Fernet

from conector_odoo.application.resources import (
    PREVIEW_MAX_LIMIT,
    CatalogResourceConfigProvider,
    DeleteResource,
    DiscoverResources,
    GetResource,
    ListResources,
    PreviewResource,
    SaveResource,
)
from conector_odoo.domain.errors import (
    CatalogResourceNotFound,
    ProfileNotFound,
    ProfileValidationError,
    ResourceConfigInvalid,
    ResourceNotFound,
)
from conector_odoo.domain.ports import ResourceConfigProvider
from conector_odoo.domain.profiles import (
    AuthMethod,
    ConnectionProfile,
    ProfileType,
    Secrets,
)
from conector_odoo.domain.records import FieldSpec, FieldType, Record, ResourceSchema
from conector_odoo.domain.resources import EndpointSpec, ResourceConfig, ResourceSource
from conector_odoo.infrastructure.migrations import open_admin_database
from conector_odoo.infrastructure.odoo.client import OdooClient
from conector_odoo.infrastructure.odoo.records import OdooRecordEndpoint
from conector_odoo.infrastructure.profiles.repository import SqliteConnectionProfileRepository
from conector_odoo.infrastructure.profiles.vault import FernetVault
from conector_odoo.infrastructure.resources.repository import SqliteResourceCatalogRepository
from tests.adapters.test_odoo_record_endpoint import FakeOdoo

SECRET = "super-secret-token-value"


class FakeEndpoint:
    def __init__(self, records: list[Record], schema: ResourceSchema) -> None:
        self.records = records
        self.schema = schema
        self.sample_limits: list[int] = []
        self.closed = False

    async def aclose(self) -> None:
        self.closed = True

    async def describe(self, resource: str) -> ResourceSchema:
        return self.schema

    async def sample(self, resource: str, limit: int) -> list[Record]:
        self.sample_limits.append(limit)
        return self.records[:limit]


class Env:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self.profiles = SqliteConnectionProfileRepository(conn)
        self.catalog = SqliteResourceCatalogRepository(conn)
        self.vault = FernetVault(Fernet.generate_key().decode())
        self.endpoint = FakeEndpoint(
            [Record(str(i), {"id": i, "name": f"n{i}"}) for i in range(50)],
            ResourceSchema("things", "Things", (FieldSpec("id", FieldType.INTEGER),)),
        )
        self.odoo = FakeOdoo()
        self.rest_args: list[tuple[ConnectionProfile, Secrets, ResourceConfigProvider]] = []
        self.save = SaveResource(self.profiles, self.catalog)
        self.list = ListResources(self.profiles, self.catalog)
        self.get = GetResource(self.catalog)
        self.delete = DeleteResource(self.catalog)
        self.preview = PreviewResource(
            self.profiles, self.catalog, self.vault, self._build_rest, self._build_odoo
        )
        self.discover = DiscoverResources(self.profiles, self.catalog, self.vault, self._build_odoo)

    def _build_rest(
        self, profile: ConnectionProfile, secrets: Secrets, configs: ResourceConfigProvider
    ) -> FakeEndpoint:
        self.rest_args.append((profile, secrets, configs))
        return self.endpoint

    def _build_odoo(self, profile: ConnectionProfile, secrets: Secrets) -> OdooRecordEndpoint:
        return OdooRecordEndpoint(OdooClient(self.odoo))

    async def add_profile(self, kind: ProfileType = ProfileType.REST, **extra: Any) -> int:
        draft = ConnectionProfile(
            id=None,
            name=f"p-{kind.value}",
            type=kind,
            base_url="https://api.test",
            auth_method=AuthMethod.BEARER,
            secret_fields=frozenset({"token"}),
            **extra,
        )
        saved = await self.profiles.add(draft, self.vault.encrypt(Secrets(token=SECRET)))
        assert saved.id is not None
        return saved.id


@pytest.fixture
def conn() -> Iterator[sqlite3.Connection]:
    connection = open_admin_database(":memory:")
    yield connection
    connection.close()


@pytest.fixture
def env(conn: sqlite3.Connection) -> Env:
    return Env(conn)


def things() -> ResourceConfig:
    return ResourceConfig(
        name="things",
        label="Things",
        list_endpoint=EndpointSpec("GET", "/things"),
        get_endpoint=EndpointSpec("GET", "/things/{id}"),
    )


async def test_save_creates_then_updates(env: Env) -> None:
    pid = await env.add_profile()
    created = await env.save.execute(pid, things())
    assert created.source is ResourceSource.MANUAL
    updated = await env.save.execute(pid, replace(things(), label="Cosas"), ResourceSource.OPENAPI)
    assert updated.config.label == "Cosas"
    assert [r.config.name for r in await env.list.execute(pid)] == ["things"]
    assert (await env.get.execute(pid, "things")).config.label == "Cosas"


async def test_save_validates_the_config(env: Env) -> None:
    pid = await env.add_profile()
    with pytest.raises(ResourceConfigInvalid):
        await env.save.execute(pid, replace(things(), get_endpoint=EndpointSpec("GET", "/t")))
    assert await env.list.execute(pid) == []


async def test_save_needs_an_existing_rest_profile(env: Env) -> None:
    with pytest.raises(ProfileNotFound):
        await env.save.execute(404, things())
    odoo = await env.add_profile(ProfileType.ODOO, odoo_db="d", odoo_login="l")
    with pytest.raises(ProfileValidationError, match="REST"):
        await env.save.execute(odoo, things())


async def test_list_needs_an_existing_profile_and_get_delete_report_missing(env: Env) -> None:
    with pytest.raises(ProfileNotFound):
        await env.list.execute(404)
    pid = await env.add_profile()
    with pytest.raises(CatalogResourceNotFound):
        await env.get.execute(pid, "nope")
    await env.save.execute(pid, things())
    await env.delete.execute(pid, "things")
    with pytest.raises(CatalogResourceNotFound):
        await env.delete.execute(pid, "things")


async def test_catalog_provider_serves_one_profile_and_raises_resource_not_found(env: Env) -> None:
    a = await env.add_profile()
    await env.save.execute(a, things())
    provider = CatalogResourceConfigProvider(env.catalog, a)
    assert (await provider.get("things")).label == "Things"
    with pytest.raises(ResourceNotFound):
        await provider.get("other")


async def test_preview_rest_returns_sample_and_schema_and_never_secrets(env: Env) -> None:
    pid = await env.add_profile()
    await env.save.execute(pid, things())
    result = await env.preview.execute(pid, "things", 3)
    assert [r.id for r in result.records] == ["0", "1", "2"]
    assert result.schema.name == "things"
    assert env.endpoint.closed
    _, secrets, provider = env.rest_args[0]
    assert secrets.token == SECRET  # decrypted only to build the endpoint
    assert isinstance(provider, CatalogResourceConfigProvider)
    assert SECRET not in repr(result)
    assert SECRET not in repr(result.schema)


@pytest.mark.parametrize(("asked", "used"), [(0, 1), (-5, 1), (7, 7), (500, PREVIEW_MAX_LIMIT)])
async def test_preview_clamps_the_limit(env: Env, asked: int, used: int) -> None:
    pid = await env.add_profile()
    await env.save.execute(pid, things())
    result = await env.preview.execute(pid, "things", asked)
    assert env.endpoint.sample_limits == [used]
    assert len(result.records) == used


async def test_preview_unknown_resource_or_profile(env: Env) -> None:
    pid = await env.add_profile()
    with pytest.raises(CatalogResourceNotFound):
        await env.preview.execute(pid, "nope", 5)
    with pytest.raises(ProfileNotFound):
        await env.preview.execute(404, "things", 5)


async def test_preview_closes_the_endpoint_on_failure(env: Env) -> None:
    pid = await env.add_profile()
    await env.save.execute(pid, things())

    async def boom(resource: str, limit: int) -> list[Record]:
        raise ResourceNotFound("remote 404")

    env.endpoint.sample = boom  # type: ignore[method-assign]
    with pytest.raises(ResourceNotFound):
        await env.preview.execute(pid, "things", 5)
    assert env.endpoint.closed


async def test_preview_odoo_uses_the_model_name_without_catalog(env: Env) -> None:
    pid = await env.add_profile(ProfileType.ODOO, odoo_db="d", odoo_login="l")
    env.odoo.rows["res.partner"] = [{"id": 1, "name": "A"}, {"id": 2, "name": "B"}]
    result = await env.preview.execute(pid, "res.partner", 1)
    assert [r.id for r in result.records] == ["1"]
    assert result.schema.name == "res.partner"


async def test_discover_odoo_lists_non_transient_models(env: Env) -> None:
    pid = await env.add_profile(ProfileType.ODOO, odoo_db="d", odoo_login="l")
    env.odoo.models["ir.model"] = {
        "id": {"type": "integer"},
        "name": {"type": "char"},
        "model": {"type": "char"},
        "transient": {"type": "boolean"},
    }
    env.odoo.rows["ir.model"] = [
        {"id": 1, "name": "Contact", "model": "res.partner", "transient": False},
        {"id": 2, "name": "Wizard", "model": "x.wizard", "transient": True},
        {"id": 3, "name": "Product", "model": "product.product", "transient": False},
    ]
    found = await env.discover.execute(pid)
    assert [(d.name, d.label) for d in found] == [
        ("product.product", "Product"),
        ("res.partner", "Contact"),
    ]
    domain = env.odoo.calls_to("search_read")[0][2][0]
    assert ["transient", "=", False] in domain


async def test_discover_rest_returns_the_catalog(env: Env) -> None:
    pid = await env.add_profile()
    await env.save.execute(pid, things())
    found = await env.discover.execute(pid)
    assert [(d.name, d.label) for d in found] == [("things", "Things")]
