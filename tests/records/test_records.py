"""Generic record model: immutability, dotted paths, schema lookup, filter defaults, errors."""

from dataclasses import FrozenInstanceError
from datetime import UTC, datetime

import pytest

from conector_odoo.domain.errors import (
    ConnectorError,
    RecordRejected,
    RemoteAuthError,
    RemoteUnavailable,
    ResourceNotFound,
)
from conector_odoo.domain.records import (
    FieldSpec,
    FieldType,
    Record,
    RecordFilter,
    RecordPage,
    ResourceSchema,
)


class TestRecord:
    def test_copies_input_so_later_mutation_is_not_seen(self) -> None:
        source: dict[str, object] = {"name": "Ana", "tags": ["a"]}
        record = Record(id="1", fields=source)
        source["name"] = "changed"
        assert record.fields["name"] == "Ana"

    def test_fields_are_read_only_and_record_is_frozen(self) -> None:
        record = Record(id="1", fields={"name": "Ana"})
        with pytest.raises(TypeError):
            record.fields["name"] = "x"  # type: ignore[index]
        with pytest.raises(FrozenInstanceError):
            record.id = "2"  # type: ignore[misc]

    def test_id_may_be_none_for_unsaved_records(self) -> None:
        assert Record(id=None, fields={}).id is None

    def test_get_top_level_and_nested_path(self) -> None:
        record = Record(id="1", fields={"name": "Ana", "address": {"city": {"name": "Madrid"}}})
        assert record.get("name") == "Ana"
        assert record.get("address.city.name") == "Madrid"

    def test_get_indexes_into_lists(self) -> None:
        record = Record(id="1", fields={"lines": [{"sku": "A"}, {"sku": "B"}]})
        assert record.get("lines.1.sku") == "B"

    def test_get_missing_path_returns_default(self) -> None:
        record = Record(id="1", fields={"address": {"city": "X"}, "lines": [1], "n": None})
        assert record.get("nope") is None
        assert record.get("address.zip", "-") == "-"
        assert record.get("address.city.deeper", "-") == "-"
        assert record.get("lines.5", "-") == "-"
        assert record.get("lines.x", "-") == "-"
        assert record.get("n.x", "-") == "-"

    def test_get_returns_none_value_not_default_when_key_exists(self) -> None:
        assert Record(id="1", fields={"n": None}).get("n", "-") is None

    def test_nested_values_are_not_mutable_through_the_record(self) -> None:
        record = Record(id="1", fields={"tags": ["a"]})
        record.get("tags")  # a copy is handed out, not the stored list
        assert record.get("tags") is not record.get("tags")


class TestSchema:
    def schema(self) -> ResourceSchema:
        return ResourceSchema(
            name="res.partner",
            label="Contact",
            fields=(
                FieldSpec("id", FieldType.INTEGER, readonly=True),
                FieldSpec("name", FieldType.STRING, required=True, label="Name"),
            ),
        )

    def test_field_defaults(self) -> None:
        spec = FieldSpec("x", FieldType.UNKNOWN)
        assert (spec.required, spec.readonly, spec.label, spec.choices, spec.relation) == (
            False,
            False,
            None,
            None,
            None,
        )

    def test_lookup(self) -> None:
        schema = self.schema()
        found = schema.field("name")
        assert found is not None and found.required
        assert schema.field("missing") is None
        assert schema.id_field == "id"

    def test_field_types(self) -> None:
        assert {t.value for t in FieldType} == {
            "string",
            "integer",
            "number",
            "boolean",
            "date",
            "datetime",
            "object",
            "array",
            "unknown",
        }


class TestFilterAndPage:
    def test_filter_defaults_are_empty(self) -> None:
        f = RecordFilter()
        assert dict(f.equals) == {} and f.since is None and f.raw is None

    def test_filter_holds_values(self) -> None:
        since = datetime(2026, 1, 1, tzinfo=UTC)
        f = RecordFilter(equals={"a": 1}, since=since, raw={"q": "x"})
        assert f.equals["a"] == 1 and f.since == since and f.raw == {"q": "x"}

    def test_page_defaults(self) -> None:
        page = RecordPage(records=(Record(id="1", fields={}),))
        assert page.next_cursor is None and page.total is None


class TestErrors:
    @pytest.mark.parametrize("cls", [ResourceNotFound, RemoteUnavailable, RemoteAuthError])
    def test_hierarchy(self, cls: type[ConnectorError]) -> None:
        assert issubclass(cls, ConnectorError)

    def test_rejected_carries_field_errors(self) -> None:
        err = RecordRejected("bad", {"email": "invalid"})
        assert isinstance(err, ConnectorError)
        assert str(err) == "bad" and err.field_errors == {"email": "invalid"}
        assert RecordRejected("bad").field_errors == {}
