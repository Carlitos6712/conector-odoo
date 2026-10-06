"""Generic Odoo record adapter, exercised over the real ``OdooClient`` and an in-memory Odoo."""

from datetime import datetime, timedelta, timezone
from typing import Any

import pytest

from conector_odoo.domain.errors import (
    OdooAuthError,
    OdooNotFound,
    OdooPermissionError,
    OdooUnavailable,
    OdooValidationError,
    ProfileValidationError,
    RecordRejected,
    RemoteAuthError,
    RemoteUnavailable,
    ResourceNotFound,
)
from conector_odoo.domain.ports import RecordEndpoint
from conector_odoo.domain.profiles import AuthMethod, ConnectionProfile, ProfileType, Secrets
from conector_odoo.domain.records import FieldType, RecordFilter
from conector_odoo.infrastructure.odoo.client import OdooClient
from conector_odoo.infrastructure.odoo.factory import build_odoo_endpoint
from conector_odoo.infrastructure.odoo.jsonrpc import JsonRpcTransport
from conector_odoo.infrastructure.odoo.records import OdooRecordEndpoint
from conector_odoo.infrastructure.odoo.xmlrpc import XmlRpcTransport

PARTNER_FIELDS: dict[str, dict[str, Any]] = {
    "id": {"type": "integer", "string": "ID", "readonly": True},
    "name": {"type": "char", "string": "Name", "required": True},
    "comment": {"type": "text", "string": "Notes"},
    "website_html": {"type": "html", "string": "Web"},
    "company_type": {
        "type": "selection",
        "string": "Type",
        "selection": [["person", "Individual"], ["company", "Company"]],
    },
    "color": {"type": "integer", "string": "Color"},
    "credit_limit": {"type": "float", "string": "Credit"},
    "balance": {"type": "monetary", "string": "Balance"},
    "active": {"type": "boolean", "string": "Active"},
    "birthday": {"type": "date", "string": "Birthday"},
    "write_date": {"type": "datetime", "string": "Updated", "readonly": True},
    "parent_id": {"type": "many2one", "string": "Parent", "relation": "res.partner"},
    "child_ids": {"type": "one2many", "string": "Contacts", "relation": "res.partner"},
    "category_id": {"type": "many2many", "string": "Tags", "relation": "res.partner.category"},
    "image_1920": {"type": "binary", "string": "Image"},
    "properties": {"type": "properties", "string": "Props"},
}


class FakeOdoo:
    """Just enough Odoo: fields_get, keyset search_read, read, create, write."""

    def __init__(self) -> None:
        self.models: dict[str, dict[str, dict[str, Any]]] = {"res.partner": PARTNER_FIELDS}
        self.rows: dict[str, list[dict[str, Any]]] = {"res.partner": []}
        self.calls: list[tuple[str, str, list[Any], dict[str, Any]]] = []
        self.failures: dict[str, BaseException] = {}
        self.next_id = 500

    async def authenticate(self) -> int:
        return 7

    async def aclose(self) -> None:
        return None

    def calls_to(self, method: str) -> list[tuple[str, str, list[Any], dict[str, Any]]]:
        return [c for c in self.calls if c[1] == method]

    async def execute_kw(
        self, model: str, method: str, args: list[Any], kwargs: dict[str, Any] | None = None
    ) -> Any:
        kw = dict(kwargs or {})
        self.calls.append((model, method, args, kw))
        if method in self.failures:
            raise self.failures[method]  # persistent: the client replays once after an auth error
        if method == "fields_get":
            return dict(self.models.get(model, {}))
        rows = self.rows.setdefault(model, [])
        if method == "search_read":
            result = [r for r in rows if all(_match(r, t) for t in args[0])]
            result.sort(key=lambda r: r["id"])
            fields = kw.get("fields")
            result = [{k: v for k, v in r.items() if not fields or k in fields} for r in result]
            return result[: kw.get("limit")]
        if method == "read":
            wanted = kw.get("fields")
            return [
                {k: v for k, v in r.items() if not wanted or k in wanted}
                for r in rows
                if r["id"] in args[0]
            ]
        if method == "create":
            payload = args[0]
            many = isinstance(payload, list)
            ids = []
            for vals in payload if many else [payload]:
                self.next_id += 1
                rows.append({"id": self.next_id, **vals})
                ids.append(self.next_id)
            return ids if many else ids[0]
        if method == "write":
            for r in rows:
                if r["id"] in args[0]:
                    r.update(args[1])
            return True
        if method == "unlink":
            before = len(rows)
            rows[:] = [r for r in rows if r["id"] not in args[0]]
            return len(rows) < before
        raise AssertionError(f"unexpected {method}")


def _match(row: dict[str, Any], term: Any) -> bool:
    if isinstance(term, str):  # a domain operator: the fake only needs to accept it
        return True
    field, op, value = term
    actual = row.get(field)
    if op == "=":
        return bool(actual == value)
    if op == ">":
        return bool(actual > value)
    if op == ">=":
        return actual not in (None, False) and bool(actual >= value)
    raise AssertionError(f"fake does not support {op}")


def partner(i: int, **extra: Any) -> dict[str, Any]:
    return {
        "id": i,
        "name": f"P{i}",
        "comment": False,
        "active": True,
        "parent_id": False,
        "birthday": False,
        "write_date": "2024-05-01 10:00:00",
        "category_id": [],
        **extra,
    }


def make(*, allow: bool = False) -> tuple[OdooRecordEndpoint, FakeOdoo]:
    odoo = FakeOdoo()
    return OdooRecordEndpoint(OdooClient(odoo), allow_system_model_writes=allow), odoo


async def collect(endpoint: OdooRecordEndpoint, flt: RecordFilter, size: int = 2) -> list[Any]:
    return [r async for batch in endpoint.iter_batches("res.partner", flt, size) for r in batch]


# -- describe ------------------------------------------------------------------------------


async def test_is_a_record_endpoint() -> None:
    endpoint, _ = make()
    assert isinstance(endpoint, RecordEndpoint)


async def test_describe_maps_every_field_type() -> None:
    endpoint, _ = make()
    schema = await endpoint.describe("res.partner")
    by = {f.name: f for f in schema.fields}
    assert schema.name == "res.partner"
    assert schema.id_field == "id"
    expected = {
        "name": FieldType.STRING,
        "comment": FieldType.STRING,
        "website_html": FieldType.STRING,
        "company_type": FieldType.STRING,
        "color": FieldType.INTEGER,
        "credit_limit": FieldType.NUMBER,
        "balance": FieldType.NUMBER,
        "active": FieldType.BOOLEAN,
        "birthday": FieldType.DATE,
        "write_date": FieldType.DATETIME,
        "parent_id": FieldType.INTEGER,
        "child_ids": FieldType.ARRAY,
        "category_id": FieldType.ARRAY,
        "image_1920": FieldType.UNKNOWN,
        "properties": FieldType.UNKNOWN,
    }
    assert {n: by[n].type for n in expected} == expected


async def test_describe_flags_labels_choices_and_relations() -> None:
    endpoint, _ = make()
    by = {f.name: f for f in (await endpoint.describe("res.partner")).fields}
    assert by["name"].required and not by["name"].readonly
    assert by["write_date"].readonly
    assert by["name"].label == "Name"
    assert by["company_type"].choices == ("person", "company")
    assert by["parent_id"].relation == "res.partner"
    assert by["category_id"].relation == "res.partner.category"
    assert by["name"].relation is None and by["name"].choices is None


async def test_describe_is_cached_per_model() -> None:
    endpoint, odoo = make()
    first = await endpoint.describe("res.partner")
    second = await endpoint.describe("res.partner")
    assert first is second
    assert len(odoo.calls_to("fields_get")) == 1


async def test_describe_unknown_model_is_resource_not_found() -> None:
    endpoint, _ = make()
    with pytest.raises(ResourceNotFound):
        await endpoint.describe("x.nope")


# -- reading ---------------------------------------------------------------------------------


async def test_iter_batches_uses_keyset_batches_and_excludes_binary_fields() -> None:
    endpoint, odoo = make()
    odoo.rows["res.partner"] = [partner(i) for i in range(1, 6)]
    records = await collect(endpoint, RecordFilter(), size=2)
    assert [r.id for r in records] == ["1", "2", "3", "4", "5"]
    searches = odoo.calls_to("search_read")
    assert len(searches) == 3
    assert searches[1][2][0][-1] == ["id", ">", 2]
    assert "image_1920" not in searches[0][3]["fields"]
    assert "name" in searches[0][3]["fields"]


async def test_batches_hold_batch_size_records() -> None:
    endpoint, odoo = make()
    odoo.rows["res.partner"] = [partner(i) for i in range(1, 6)]
    sizes = [len(b) async for b in endpoint.iter_batches("res.partner", RecordFilter(), 2)]
    assert sizes == [2, 2, 1]


async def test_values_are_normalized() -> None:
    endpoint, odoo = make()
    odoo.rows["res.partner"] = [
        partner(1, parent_id=[9, "Acme"], category_id=[3, 4], comment="hi", birthday="2000-01-02"),
        partner(2, active=False),
    ]
    first, second = await collect(endpoint, RecordFilter())
    assert first.id == "1"
    assert first.fields["id"] == 1
    assert first.fields["parent_id"] == 9 and type(first.fields["parent_id"]) is int
    assert first.fields["category_id"] == [3, 4]
    assert first.fields["birthday"] == "2000-01-02"
    assert first.fields["comment"] == "hi"
    assert second.fields["comment"] is None
    assert second.fields["parent_id"] is None
    assert second.fields["birthday"] is None
    assert second.fields["active"] is False  # False stays False on a boolean field


async def test_filter_equals_since_and_raw_domain_are_combined() -> None:
    endpoint, odoo = make()
    since = datetime(2024, 5, 1, 12, 30, tzinfo=timezone(timedelta(hours=2)))
    flt = RecordFilter(
        equals={"name": "P1"},
        since=since,
        raw={"domain": [["active", "=", True], "|", ["color", "=", 1], ["color", "=", 2]]},
    )
    await collect(endpoint, flt)
    domain = odoo.calls_to("search_read")[0][2][0]
    assert ["name", "=", "P1"] in domain
    assert ["write_date", ">=", "2024-05-01 10:30:00"] in domain  # converted to UTC, Odoo format
    assert domain[-4:] == [["active", "=", True], "|", ["color", "=", 1], ["color", "=", 2]]


@pytest.mark.parametrize(
    "raw",
    [
        {"domain": "name = x"},
        {"domain": [["name", "="]]},
        {"domain": [["name", "banana", 1]]},
        {"domain": [[1, "=", 1]]},
        {"domain": ["xor"]},
        {"other": 1},
    ],
)
async def test_invalid_raw_domain_is_rejected_before_any_call(raw: dict[str, Any]) -> None:
    endpoint, odoo = make()
    with pytest.raises(RecordRejected):
        await collect(endpoint, RecordFilter(raw=raw))
    assert odoo.calls_to("search_read") == []


async def test_filter_on_unknown_field_is_rejected() -> None:
    endpoint, _ = make()
    with pytest.raises(RecordRejected, match="nope"):
        await collect(endpoint, RecordFilter(equals={"nope": 1}))


async def test_naive_since_is_taken_as_utc() -> None:
    endpoint, odoo = make()
    await collect(endpoint, RecordFilter(since=datetime(2024, 1, 2, 3, 4, 5)))
    assert ["write_date", ">=", "2024-01-02 03:04:05"] in odoo.calls_to("search_read")[0][2][0]


async def test_get_returns_a_record_or_none() -> None:
    endpoint, odoo = make()
    odoo.rows["res.partner"] = [partner(1, parent_id=[9, "A"])]
    got = await endpoint.get("res.partner", "1")
    assert got is not None and got.id == "1" and got.fields["parent_id"] == 9
    assert await endpoint.get("res.partner", "2") is None
    assert await endpoint.get("res.partner", "abc") is None


async def test_get_missing_record_error_is_none() -> None:
    endpoint, odoo = make()
    odoo.failures["read"] = OdooNotFound("gone")
    assert await endpoint.get("res.partner", "1") is None


async def test_sample_returns_at_most_limit() -> None:
    endpoint, odoo = make()
    odoo.rows["res.partner"] = [partner(i) for i in range(1, 6)]
    assert [r.id for r in await endpoint.sample("res.partner", 3)] == ["1", "2", "3"]
    assert odoo.calls_to("search_read")[0][3]["limit"] == 3


async def test_find_by_returns_first_match_or_none() -> None:
    endpoint, odoo = make()
    odoo.rows["res.partner"] = [partner(1, name="A"), partner(2, name="B")]
    found = await endpoint.find_by("res.partner", "name", "B")
    assert found is not None and found.id == "2"
    assert odoo.calls_to("search_read")[0][3]["limit"] == 1
    assert await endpoint.find_by("res.partner", "name", "Z") is None


async def test_find_by_none_searches_for_false() -> None:
    endpoint, odoo = make()
    await endpoint.find_by("res.partner", "comment", None)
    assert ["comment", "=", False] in odoo.calls_to("search_read")[0][2][0]


# -- writing ---------------------------------------------------------------------------------


async def test_create_converts_values_and_returns_the_record() -> None:
    endpoint, odoo = make()
    created = await endpoint.create(
        "res.partner",
        {
            "name": "New",
            "comment": None,
            "parent_id": "9",
            "birthday": None,
            "active": None,
            "category_id": [3, 4],
            "child_ids": [[0, 0, {"name": "kid"}]],
        },
        idempotency_key="k-1",
    )
    sent = odoo.calls_to("create")[0][2][0]
    assert sent == {
        "name": "New",
        "comment": False,
        "parent_id": 9,
        "birthday": False,
        "active": False,
        "category_id": [[6, 0, [3, 4]]],
        "child_ids": [[0, 0, {"name": "kid"}]],
    }
    assert created.id == "501"
    assert created.fields["name"] == "New"


async def test_create_accepts_and_ignores_the_idempotency_key() -> None:
    endpoint, odoo = make()
    await endpoint.create("res.partner", {"name": "A"}, idempotency_key="same")
    await endpoint.create("res.partner", {"name": "A"}, idempotency_key="same")
    assert len(odoo.calls_to("create")) == 2  # Odoo has no idempotency: dedupe is the sync layer's
    assert "same" not in repr(odoo.calls)


async def test_create_with_unknown_field_is_rejected_with_field_errors() -> None:
    endpoint, odoo = make()
    with pytest.raises(RecordRejected) as info:
        await endpoint.create("res.partner", {"name": "A", "bogus": 1}, idempotency_key="k")
    assert "bogus" in info.value.field_errors
    assert odoo.calls_to("create") == []


async def test_create_survives_an_unreadable_record_after_success() -> None:
    endpoint, odoo = make()
    odoo.failures["read"] = OdooUnavailable("boom")
    created = await endpoint.create("res.partner", {"name": "A"}, idempotency_key="k")
    assert created.id == "501" and created.fields["name"] == "A"


async def test_update_writes_and_returns_the_record() -> None:
    endpoint, odoo = make()
    odoo.rows["res.partner"] = [partner(1)]
    updated = await endpoint.update("res.partner", "1", {"name": "Renamed", "parent_id": None})
    assert odoo.calls_to("write")[0][2] == [[1], {"name": "Renamed", "parent_id": False}]
    assert updated.id == "1" and updated.fields["name"] == "Renamed"
    assert updated.fields["parent_id"] is None


async def test_update_of_a_missing_record_is_resource_not_found() -> None:
    endpoint, odoo = make()
    odoo.failures["write"] = OdooNotFound("gone")
    with pytest.raises(ResourceNotFound):
        await endpoint.update("res.partner", "1", {"name": "x"})


async def test_update_with_non_numeric_id_is_resource_not_found() -> None:
    endpoint, odoo = make()
    with pytest.raises(ResourceNotFound):
        await endpoint.update("res.partner", "abc", {"name": "x"})
    assert odoo.calls_to("write") == []


async def test_delete_unlinks_the_record_for_real() -> None:
    endpoint, odoo = make()
    odoo.rows["res.partner"] = [partner(1), partner(2)]
    await endpoint.delete("res.partner", "1")
    assert [c[2] for c in odoo.calls_to("unlink")] == [[[1]]]
    assert odoo.calls_to("write") == []  # a real delete, not the client's archive shortcut
    assert [r["id"] for r in odoo.rows["res.partner"]] == [2]


async def test_delete_of_a_missing_record_is_resource_not_found_and_does_not_unlink() -> None:
    endpoint, odoo = make()
    with pytest.raises(ResourceNotFound, match="999"):
        await endpoint.delete("res.partner", "999")
    assert odoo.calls_to("unlink") == []


async def test_delete_with_non_numeric_id_is_resource_not_found() -> None:
    endpoint, odoo = make()
    with pytest.raises(ResourceNotFound):
        await endpoint.delete("res.partner", "abc")
    assert odoo.calls_to("unlink") == []


async def test_delete_of_a_referenced_record_is_a_clear_record_rejected() -> None:
    endpoint, odoo = make()
    odoo.rows["res.partner"] = [partner(1)]
    odoo.failures["unlink"] = OdooValidationError("You cannot delete a partner with invoices")
    with pytest.raises(RecordRejected, match="invoices") as raised:
        await endpoint.delete("res.partner", "1")
    assert "res.partner" in str(raised.value) and "1" in str(raised.value)


async def test_delete_access_denied_is_record_rejected_not_an_auth_failure() -> None:
    endpoint, odoo = make()
    odoo.rows["res.partner"] = [partner(1)]
    odoo.failures["unlink"] = OdooPermissionError("no unlink right")
    with pytest.raises(RecordRejected, match="access"):
        await endpoint.delete("res.partner", "1")


async def test_delete_record_gone_between_check_and_unlink_is_resource_not_found() -> None:
    endpoint, odoo = make()
    odoo.rows["res.partner"] = [partner(1)]
    odoo.failures["unlink"] = OdooNotFound("gone")
    with pytest.raises(ResourceNotFound):
        await endpoint.delete("res.partner", "1")


async def test_delete_unavailable_propagates_as_remote_unavailable() -> None:
    endpoint, odoo = make()
    odoo.rows["res.partner"] = [partner(1)]
    odoo.failures["unlink"] = OdooUnavailable("boom")
    with pytest.raises(RemoteUnavailable):
        await endpoint.delete("res.partner", "1")


@pytest.mark.parametrize("model", ["ir.config_parameter", "res.users", "ir.actions.server"])
async def test_dangerous_models_cannot_be_deleted_by_default(model: str) -> None:
    endpoint, odoo = make()
    odoo.models[model] = {"name": {"type": "char", "string": "Name"}}
    with pytest.raises(RecordRejected, match="allow_system_model_writes"):
        await endpoint.delete(model, "1")
    assert odoo.calls_to("unlink") == []


# -- errors ----------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("raised", "expected"),
    [
        (OdooAuthError("bad key"), RemoteAuthError),
        (OdooPermissionError("no access"), RemoteAuthError),
        (OdooUnavailable("down"), RemoteUnavailable),
        (OdooValidationError("invalid"), RecordRejected),
        (OdooNotFound("model gone"), ResourceNotFound),
    ],
)
async def test_odoo_errors_are_mapped_at_the_boundary(
    raised: Exception, expected: type[Exception]
) -> None:
    endpoint, odoo = make()
    await endpoint.describe("res.partner")
    odoo.failures["search_read"] = raised
    with pytest.raises(expected):
        await collect(endpoint, RecordFilter())


async def test_validation_error_extracts_field_errors_best_effort() -> None:
    endpoint, odoo = make()
    odoo.failures["create"] = OdooValidationError(
        "Invalid fields:\n- Name (name): is required\n- something else"
    )
    with pytest.raises(RecordRejected) as info:
        await endpoint.create("res.partner", {"name": ""}, idempotency_key="k")
    assert "required" in info.value.field_errors["name"]


async def test_describe_errors_are_mapped_too() -> None:
    endpoint, odoo = make()
    odoo.failures["fields_get"] = OdooAuthError("bad key")
    with pytest.raises(RemoteAuthError):
        await endpoint.describe("res.partner")


# -- model safety ----------------------------------------------------------------------------


@pytest.mark.parametrize(
    "model",
    [
        "ir.config_parameter",
        "ir.rule",
        "ir.model.access",
        "res.users",
        "ir.cron",
        "ir.actions.server",
        "ir.actions.act_window",
        "base.module.upgrade",
    ],
)
async def test_dangerous_models_are_not_writable_by_default(model: str) -> None:
    endpoint, odoo = make()
    odoo.models[model] = {"name": {"type": "char", "string": "Name"}}
    with pytest.raises(RecordRejected, match="allow_system_model_writes"):
        await endpoint.create(model, {"name": "x"}, idempotency_key="k")
    with pytest.raises(RecordRejected, match="allow_system_model_writes"):
        await endpoint.update(model, "1", {"name": "x"})
    assert odoo.calls_to("create") == [] and odoo.calls_to("write") == []


async def test_dangerous_models_can_be_read() -> None:
    endpoint, odoo = make()
    odoo.models["res.users"] = {"id": {"type": "integer", "string": "ID"}}
    odoo.rows["res.users"] = [{"id": 1}]
    assert (await endpoint.get("res.users", "1")) is not None


async def test_flag_allows_system_model_writes() -> None:
    endpoint, odoo = make(allow=True)
    odoo.models["ir.config_parameter"] = {"key": {"type": "char", "string": "Key"}}
    created = await endpoint.create("ir.config_parameter", {"key": "a"}, idempotency_key="k")
    assert created.id == "501"


async def test_similar_but_safe_models_are_writable() -> None:
    endpoint, odoo = make()
    odoo.models["res.users.log"] = {"name": {"type": "char", "string": "N"}}
    odoo.models["ir.attachment"] = {"name": {"type": "char", "string": "N"}}
    await endpoint.create("ir.attachment", {"name": "x"}, idempotency_key="k")


# -- factory ---------------------------------------------------------------------------------


def odoo_profile(**overrides: Any) -> ConnectionProfile:
    values: dict[str, Any] = {
        "id": None,
        "name": "o",
        "type": ProfileType.ODOO,
        "base_url": "https://odoo.test",
        "auth_method": AuthMethod.API_KEY,
        "odoo_db": "prod",
        "odoo_login": "admin",
    }
    values.update(overrides)
    return ConnectionProfile(**values)


async def test_factory_builds_an_endpoint_without_leaking_secrets() -> None:
    endpoint = build_odoo_endpoint(odoo_profile(), Secrets(api_key="super-secret-key"))
    assert isinstance(endpoint, OdooRecordEndpoint)
    assert isinstance(endpoint, RecordEndpoint)
    assert "super-secret-key" not in repr(endpoint)
    assert "super-secret-key" not in repr(endpoint._client._transport)
    await endpoint.aclose()


async def test_factory_selects_transport_and_accepts_password() -> None:
    default = build_odoo_endpoint(odoo_profile(), Secrets(password="pw"))
    assert isinstance(default._client._transport, JsonRpcTransport)
    xml = build_odoo_endpoint(odoo_profile(), Secrets(api_key="k"), protocol="xmlrpc")
    assert isinstance(xml._client._transport, XmlRpcTransport)
    await default.aclose()
    await xml.aclose()


async def test_factory_forwards_the_safety_flag() -> None:
    endpoint = build_odoo_endpoint(
        odoo_profile(), Secrets(api_key="k"), allow_system_model_writes=True
    )
    assert endpoint._allow_system_writes is True
    await endpoint.aclose()


@pytest.mark.parametrize(
    ("profile", "secrets", "error"),
    [
        (odoo_profile(odoo_db=None), Secrets(api_key="k"), ProfileValidationError),
        (odoo_profile(odoo_login=None), Secrets(api_key="k"), ProfileValidationError),
        (odoo_profile(), Secrets(), RemoteAuthError),
        (
            odoo_profile(type=ProfileType.REST, auth_method=AuthMethod.BEARER),
            Secrets(token="t"),
            ProfileValidationError,
        ),
    ],
)
def test_factory_rejects_incomplete_profiles(
    profile: ConnectionProfile, secrets: Secrets, error: type[Exception]
) -> None:
    with pytest.raises(error):
        build_odoo_endpoint(profile, secrets)
