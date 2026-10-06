"""Model-generic ``RecordSource`` + ``RecordSink`` over any Odoo model.

The resource name IS the Odoo model name (``res.partner``); the schema is discovered with
``fields_get`` and cached for the endpoint lifetime. Transport selection, retries, the
concurrency semaphore and keyset batching all come from the wrapped ``OdooClient``.

Odoo has no native idempotency key: ``create`` accepts ``idempotency_key`` to honour the
``RecordSink`` contract and ignores it. Replay protection is the sync layer's job (``find_by`` on
the upsert key plus the cross-reference table, task B8).

Write safety: creating/updating records of clearly dangerous system models (see
``WRITE_DENYLIST``) is rejected unless the endpoint is built with
``allow_system_model_writes=True``. Reads are never restricted here (Odoo access rights apply).
"""

import asyncio
import re
from collections.abc import AsyncIterator, Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from conector_odoo.domain.errors import (
    OdooAuthError,
    OdooNotFound,
    OdooPermissionError,
    OdooUnavailable,
    OdooValidationError,
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
    ResourceSchema,
)
from conector_odoo.infrastructure.odoo.client import OdooClient

# Exact model names and name prefixes whose records must not be written by a generic sync.
WRITE_DENYLIST_EXACT = frozenset(
    {"ir.config_parameter", "ir.rule", "ir.model.access", "res.users", "ir.cron"}
)
WRITE_DENYLIST_PREFIXES = ("ir.actions.", "base.module.")

_TYPE_MAP = {
    "char": FieldType.STRING,
    "text": FieldType.STRING,
    "html": FieldType.STRING,
    "selection": FieldType.STRING,
    "integer": FieldType.INTEGER,
    "float": FieldType.NUMBER,
    "monetary": FieldType.NUMBER,
    "boolean": FieldType.BOOLEAN,
    "date": FieldType.DATE,
    "datetime": FieldType.DATETIME,
    "many2one": FieldType.INTEGER,
    "one2many": FieldType.ARRAY,
    "many2many": FieldType.ARRAY,
}
_FIELD_ATTRIBUTES = ["string", "type", "required", "readonly", "selection", "relation"]
_DOMAIN_OPERATORS = frozenset(
    {"=", "!=", ">", ">=", "<", "<=", "=?", "=like", "=ilike", "like", "not like", "ilike"}
    | {"not ilike", "in", "not in", "child_of", "parent_of"}
)
_LOGIC = frozenset({"&", "|", "!"})
_FIELD_IN_PARENS = re.compile(r"\(([a-z_][a-z0-9_]*)\)")
_FIELD_IN_COLUMN = re.compile(r'column "([a-z_][a-z0-9_]*)"')


@dataclass(frozen=True, slots=True)
class _ModelInfo:
    schema: ResourceSchema
    read_fields: tuple[str, ...]  # everything except binary fields (can be huge)
    kinds: Mapping[str, str]  # field name -> raw Odoo type


class OdooRecordEndpoint:
    def __init__(self, client: OdooClient, *, allow_system_model_writes: bool = False) -> None:
        self._client = client
        self._allow_system_writes = allow_system_model_writes
        self._models: dict[str, _ModelInfo] = {}
        self._lock = asyncio.Lock()

    def __repr__(self) -> str:
        return f"OdooRecordEndpoint(allow_system_model_writes={self._allow_system_writes})"

    async def aclose(self) -> None:
        await self._client.aclose()

    # -- RecordSource ----------------------------------------------------------------------

    async def describe(self, resource: str) -> ResourceSchema:
        return (await self._info(resource)).schema

    async def iter_batches(
        self, resource: str, record_filter: RecordFilter, batch_size: int
    ) -> AsyncIterator[list[Record]]:
        info = await self._info(resource)
        domain = _domain(info, record_filter)
        with _translated():
            async for rows in self._client.iter_search_read(
                resource, domain, list(info.read_fields), batch_size=batch_size
            ):
                yield [_record(info, row) for row in rows]

    async def get(self, resource: str, id: str) -> Record | None:
        info = await self._info(resource)
        record_id = _int_id(id)
        if record_id is None:
            return None
        try:
            with _translated():
                rows = await self._client.read(resource, [record_id], list(info.read_fields))
        except ResourceNotFound:
            return None  # the model exists (describe succeeded), so this is a missing record
        return _record(info, rows[0]) if rows else None

    async def sample(self, resource: str, limit: int) -> list[Record]:
        info = await self._info(resource)
        with _translated():
            rows = await self._client.search_read(
                resource, [], list(info.read_fields), limit=limit, order="id asc"
            )
        return [_record(info, row) for row in rows]

    # -- RecordSink ------------------------------------------------------------------------

    async def find_by(self, resource: str, field: str, value: Any) -> Record | None:
        info = await self._info(resource)
        _require_fields(info, [field])
        domain = [[field, "=", _to_odoo(info, field, value)]]
        with _translated():
            rows = await self._client.search_read(
                resource, domain, list(info.read_fields), limit=1, order="id asc"
            )
        return _record(info, rows[0]) if rows else None

    async def create(self, resource: str, fields: dict[str, Any], idempotency_key: str) -> Record:
        """Create a record. ``idempotency_key`` is accepted and ignored (see module docstring)."""
        self._check_writable(resource)
        info = await self._info(resource)
        values = _values(info, fields)
        with _translated(fields):
            new_id = await self._client.create(resource, values)
        try:
            return await self._read_back(resource, info, new_id)
        except (RemoteUnavailable, RemoteAuthError, ResourceNotFound):
            # The record exists: never raise here, a retry would duplicate it.
            return Record(str(new_id), {"id": new_id, **fields})

    async def update(self, resource: str, id: str, fields: dict[str, Any]) -> Record:
        self._check_writable(resource)
        info = await self._info(resource)
        record_id = _int_id(id)
        if record_id is None:
            raise ResourceNotFound(f"{resource}: no record with id {id!r}")
        values = _values(info, fields)
        with _translated(fields):
            await self._client.write(resource, [record_id], values)
        return await self._read_back(resource, info, record_id)

    async def delete(self, resource: str, id: str) -> None:
        """Permanently remove ONE record with Odoo ``unlink`` (not the client's archive shortcut).

        Odoo's ``unlink`` silently succeeds for ids that do not exist, so existence is checked
        first: a missing record is ``ResourceNotFound``, never a silent success. Refusals (record
        referenced elsewhere, access rules) are ``RecordRejected`` with Odoo's own message.
        """
        self._check_writable(resource)
        await self._info(resource)  # unknown model -> ResourceNotFound
        record_id = _int_id(id)
        if record_id is None:
            raise ResourceNotFound(f"{resource}: no record with id {id!r}")
        with _translated():
            found = await self._client.execute_kw(
                resource, "read", [[record_id]], {"fields": ["id"]}
            )
        if not found:
            raise ResourceNotFound(f"{resource}: record {record_id} not found")
        try:
            with _translated():
                try:
                    await self._client.execute_kw(resource, "unlink", [[record_id]])
                except OdooPermissionError as exc:  # a per-record refusal, not a bad session
                    raise OdooValidationError(f"access denied: {exc}") from None
        except RecordRejected as exc:
            raise RecordRejected(f"cannot delete {resource} {record_id}: {exc}") from None
        except ResourceNotFound:
            raise ResourceNotFound(f"{resource}: record {record_id} not found") from None

    # -- internals -------------------------------------------------------------------------

    def _check_writable(self, model: str) -> None:
        if self._allow_system_writes:
            return
        if model in WRITE_DENYLIST_EXACT or model.startswith(WRITE_DENYLIST_PREFIXES):
            raise RecordRejected(
                f"writing to the system model {model!r} is blocked; build the endpoint with "
                "allow_system_model_writes=True to allow it"
            )

    async def _read_back(self, model: str, info: _ModelInfo, record_id: int) -> Record:
        with _translated():
            rows = await self._client.read(model, [record_id], list(info.read_fields))
        if not rows:
            raise ResourceNotFound(f"{model}: record {record_id} not found")
        return _record(info, rows[0])

    async def _info(self, model: str) -> _ModelInfo:
        cached = self._models.get(model)
        if cached is not None:
            return cached
        async with self._lock:
            if model not in self._models:
                with _translated():
                    raw = await self._client.execute_kw(
                        model, "fields_get", [], {"attributes": _FIELD_ATTRIBUTES}
                    )
                if not isinstance(raw, dict) or not raw:
                    raise ResourceNotFound(f"unknown Odoo model {model!r}")
                self._models[model] = _build_info(model, raw)
            return self._models[model]


# -- schema --------------------------------------------------------------------------------


def _build_info(model: str, raw: Mapping[str, Mapping[str, Any]]) -> _ModelInfo:
    specs: list[FieldSpec] = []
    kinds: dict[str, str] = {}
    for name in sorted(raw):
        meta = raw[name]
        kind = str(meta.get("type", ""))
        kinds[name] = kind
        selection = meta.get("selection")
        choices = (
            tuple(str(item[0]) for item in selection)
            if kind == "selection" and isinstance(selection, list)
            else None
        )
        relation = meta.get("relation") if kind in ("many2one", "one2many", "many2many") else None
        specs.append(
            FieldSpec(
                name=name,
                type=_TYPE_MAP.get(kind, FieldType.UNKNOWN),
                required=bool(meta.get("required")),
                readonly=bool(meta.get("readonly")),
                label=meta.get("string") or None,
                choices=choices,
                relation=relation or None,
            )
        )
    read_fields = tuple(dict.fromkeys(["id", *(n for n in sorted(raw) if kinds[n] != "binary")]))
    return _ModelInfo(ResourceSchema(model, model, tuple(specs)), read_fields, kinds)


# -- reading helpers -----------------------------------------------------------------------


def _record(info: _ModelInfo, row: Mapping[str, Any]) -> Record:
    values = {name: _from_odoo(info.kinds.get(name), value) for name, value in row.items()}
    return Record(str(row["id"]), values)


def _from_odoo(kind: str | None, value: Any) -> Any:
    if kind == "boolean":
        return value
    if value is False:
        return None
    if kind == "many2one" and isinstance(value, list | tuple):
        return int(value[0]) if value else None
    return value


def _int_id(value: str) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _require_fields(info: _ModelInfo, names: Any) -> None:
    unknown = sorted(n for n in names if n not in info.kinds)
    if unknown:
        raise RecordRejected(
            f"{info.schema.name} has no field(s) {', '.join(unknown)}",
            {n: "unknown field" for n in unknown},
        )


def _domain(info: _ModelInfo, flt: RecordFilter) -> list[Any]:
    _require_fields(info, flt.equals)
    domain: list[Any] = [[n, "=", _to_odoo(info, n, v)] for n, v in flt.equals.items()]
    if flt.since is not None:
        domain.append(["write_date", ">=", _odoo_datetime(flt.since)])
    if flt.raw:
        extra = set(flt.raw) - {"domain"}
        if extra:
            raise RecordRejected(f"unsupported raw filter keys {sorted(extra)}; use 'domain'")
        domain.extend(_validated_domain(flt.raw.get("domain", [])))
    return domain


def _odoo_datetime(value: datetime) -> str:
    if value.tzinfo is not None:
        value = value.astimezone(UTC).replace(tzinfo=None)
    return value.strftime("%Y-%m-%d %H:%M:%S")


def _validated_domain(domain: Any) -> list[Any]:
    """Accept only a list of ``&|!`` operators and ``[field, operator, value]`` triples."""
    if not isinstance(domain, list):
        raise RecordRejected("the raw Odoo domain must be a list")
    for term in domain:
        if isinstance(term, str):
            if term not in _LOGIC:
                raise RecordRejected(f"invalid domain operator {term!r}")
            continue
        if (
            not isinstance(term, list | tuple)
            or len(term) != 3
            or not isinstance(term[0], str)
            or not term[0]
            or term[1] not in _DOMAIN_OPERATORS
        ):
            raise RecordRejected(f"invalid domain term {term!r}: expected [field, operator, value]")
    return [list(t) if isinstance(t, tuple) else t for t in domain]


# -- writing helpers -----------------------------------------------------------------------


def _values(info: _ModelInfo, fields: Mapping[str, Any]) -> dict[str, Any]:
    _require_fields(info, fields)
    return {name: _to_odoo(info, name, value) for name, value in fields.items()}


def _to_odoo(info: _ModelInfo, name: str, value: Any) -> Any:
    """``None`` becomes ``False`` (how Odoo clears a field); relations are normalized."""
    if value is None:
        return False
    kind = info.kinds.get(name)
    if kind == "many2one":
        if isinstance(value, list | tuple) and value:
            return int(value[0])  # [id, display_name] as read from Odoo
        if isinstance(value, str) and value.strip().isdigit():
            return int(value)
    if kind == "many2many" and isinstance(value, list) and all(_is_id(v) for v in value):
        return [[6, 0, [int(v) for v in value]]]  # plain id list -> replace command
    return value


def _is_id(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


# -- error mapping -------------------------------------------------------------------------


@contextmanager
def _translated(sent: Mapping[str, Any] | None = None) -> Iterator[None]:
    """Map Odoo client errors to the domain errors of the record ports."""
    try:
        yield
    except (OdooAuthError, OdooPermissionError) as exc:
        raise RemoteAuthError(str(exc)) from None
    except OdooNotFound as exc:
        raise ResourceNotFound(str(exc)) from None
    except OdooValidationError as exc:
        raise RecordRejected(str(exc), _field_errors(str(exc), sent or {})) from None
    except OdooUnavailable as exc:
        raise RemoteUnavailable(str(exc)) from None


def _field_errors(message: str, sent: Mapping[str, Any]) -> dict[str, str]:
    """Best effort: Odoo names fields as ``Label (field_name)`` or ``column "field_name"``."""
    errors: dict[str, str] = {}
    for line in message.splitlines():
        for match in (*_FIELD_IN_PARENS.findall(line), *_FIELD_IN_COLUMN.findall(line)):
            if match in sent:
                errors.setdefault(match, line.strip(" -"))
    return errors
