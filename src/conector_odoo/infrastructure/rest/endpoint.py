"""``RecordSource`` + ``RecordSink`` over a generic REST API, driven by ``ResourceConfig``."""

import re
from collections.abc import AsyncIterator, Mapping
from datetime import datetime
from typing import Any
from urllib.parse import quote

from conector_odoo.domain.errors import RecordRejected, RemoteUnavailable, ResourceNotFound
from conector_odoo.domain.ports import ResourceConfigProvider
from conector_odoo.domain.records import (
    FieldSpec,
    FieldType,
    Record,
    RecordFilter,
    ResourceSchema,
)
from conector_odoo.domain.resources import (
    EndpointSpec,
    PaginationStrategy,
    ResourceConfig,
)
from conector_odoo.infrastructure.rest.http import RestHttpClient
from conector_odoo.infrastructure.rest.jsonpath import MISSING, dig

_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_TOTAL_PATHS = ("total", "count", "meta.total", "pagination.total")
_TOTAL_PAGES_PATHS = ("total_pages", "meta.total_pages", "pagination.total_pages", "pages")
_DATETIME = re.compile(r"^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}")


class RestRecordEndpoint:
    def __init__(
        self,
        http: RestHttpClient,
        configs: ResourceConfigProvider,
        *,
        scan_batch_size: int = 100,
    ) -> None:
        self._http = http
        self._configs = configs
        self._scan_batch_size = scan_batch_size
        self.warnings: list[str] = []  # non-fatal findings, deduplicated, read by preview/runner

    async def aclose(self) -> None:
        await self._http.aclose()

    # -- RecordSource ----------------------------------------------------------------------

    async def describe(self, resource: str) -> ResourceSchema:
        cfg = await self._configs.get(resource)
        fields = cfg.schema_fields
        if not fields:
            sample = await self.sample(resource, 1)
            fields = _infer_fields(sample[0]) if sample else ()
        return ResourceSchema(cfg.name, cfg.label, fields, cfg.id_field)

    async def iter_batches(
        self, resource: str, record_filter: RecordFilter, batch_size: int
    ) -> AsyncIterator[list[Record]]:
        cfg = await self._configs.get(resource)
        params, local = _filter_params(cfg, record_filter)
        async for page in self._pages(cfg, params, batch_size):
            for start in range(0, len(page), batch_size):
                batch = [r for r in page[start : start + batch_size] if _matches(r, local)]
                if batch:
                    yield batch

    async def get(self, resource: str, id: str) -> Record | None:
        cfg = await self._configs.get(resource)
        spec = cfg.get_endpoint
        if spec is None:
            return await self._get_from_list(cfg, id)
        try:
            response = await self._http.request(spec.method, _path(spec, id))
        except ResourceNotFound:
            return None
        return _record(cfg, dig(_body(response), cfg.item_path), id)

    async def _get_from_list(self, cfg: ResourceConfig, id: str) -> Record | None:
        """Resources without a get endpoint: scan the list (honoring pagination) for ``id``."""
        async for page in self._pages(cfg, {}, self._scan_batch_size):
            for record in page:
                if record.id == id:
                    return record
        return None

    async def sample(self, resource: str, limit: int) -> list[Record]:
        async for batch in self.iter_batches(resource, RecordFilter(), limit):
            return batch[:limit]
        return []

    # -- RecordSink ------------------------------------------------------------------------

    async def find_by(self, resource: str, field: str, value: Any) -> Record | None:
        flt = RecordFilter(equals={field: value})
        async for batch in self.iter_batches(resource, flt, self._scan_batch_size):
            for record in batch:
                if _same(record.get(field), value):
                    return record
        return None

    async def create(self, resource: str, fields: dict[str, Any], idempotency_key: str) -> Record:
        cfg = await self._configs.get(resource)
        spec = _require(cfg.create_endpoint, cfg, "create")
        response = await self._http.request(
            spec.method, _path(spec, None), json=fields, idempotency_key=idempotency_key
        )
        return _written(cfg, response.content, response, fields, None)

    async def update(self, resource: str, id: str, fields: dict[str, Any]) -> Record:
        cfg = await self._configs.get(resource)
        spec = _require(cfg.update_endpoint, cfg, "update")
        response = await self._http.request(spec.method, _path(spec, id), json=fields)
        return _written(cfg, response.content, response, fields, id)

    async def delete(self, resource: str, id: str) -> None:
        """404 surfaces as ``ResourceNotFound``; callers decide whether "already gone" is fine."""
        cfg = await self._configs.get(resource)
        spec = _require(cfg.delete_endpoint, cfg, "delete")
        await self._http.request(spec.method, _path(spec, id))

    # -- pagination ------------------------------------------------------------------------

    async def _pages(
        self, cfg: ResourceConfig, params: dict[str, Any], size: int
    ) -> AsyncIterator[list[Record]]:
        spec = _require(cfg.list_endpoint, cfg, "list")
        strategies = {
            PaginationStrategy.PAGE: self._page_strategy,
            PaginationStrategy.OFFSET: self._offset_strategy,
            PaginationStrategy.CURSOR: self._cursor_strategy,
            PaginationStrategy.NONE: self._single_page,
        }
        async for records in strategies[cfg.pagination.strategy](cfg, spec, params, size):
            yield records

    async def _fetch_page(
        self, cfg: ResourceConfig, spec: EndpointSpec, query: dict[str, Any]
    ) -> tuple[list[Record], Any]:
        body = _body(await self._http.request(spec.method, spec.path, params=query))
        items = dig(body, cfg.items_path)
        if not isinstance(items, list):
            raise RemoteUnavailable(
                f"{cfg.name}: the list response has no array at items_path {cfg.items_path!r}"
            )
        return [_record(cfg, item, None) for item in items], body

    async def _single_page(
        self, cfg: ResourceConfig, spec: EndpointSpec, params: dict[str, Any], size: int
    ) -> AsyncIterator[list[Record]]:
        records, body = await self._fetch_page(cfg, spec, dict(params))
        self._warn_if_truncated(cfg, body, len(records))
        if records:
            yield records

    def _warn_if_truncated(self, cfg: ResourceConfig, body: Any, returned: int) -> None:
        """The strategy is ``none`` but the response itself proves there are more records."""
        pg = cfg.pagination
        total = _first_int(body, (pg.total_path, *_TOTAL_PATHS))
        total_pages = _first_int(body, (pg.total_pages_path, *_TOTAL_PAGES_PATHS))
        if total is not None and total > returned:
            detail = f"the response reports {total} records but only {returned} were returned"
        elif total_pages is not None and total_pages > 1:
            detail = f"the response reports {total_pages} pages but only the first was read"
        else:
            return
        message = f"{cfg.name}: {detail}; set a pagination strategy to read them all"
        if message not in self.warnings:
            self.warnings.append(message)

    async def _page_strategy(
        self, cfg: ResourceConfig, spec: EndpointSpec, params: dict[str, Any], size: int
    ) -> AsyncIterator[list[Record]]:
        pg = cfg.pagination
        page_no = pg.first_page
        previous: list[str] | None = None
        for _ in range(pg.max_pages):
            query = {**params, pg.page_param: page_no, pg.size_param: size}
            records, body = await self._fetch_page(cfg, spec, query)
            if not records:
                return
            previous = _check_not_repeated(cfg, records, previous)
            yield records
            total_pages = dig(body, pg.total_pages_path)
            if isinstance(total_pages, int):
                if page_no - pg.first_page + 1 >= total_pages:
                    return
            elif len(records) < size:
                return
            page_no += 1
        raise _exceeded(cfg)

    async def _offset_strategy(
        self, cfg: ResourceConfig, spec: EndpointSpec, params: dict[str, Any], size: int
    ) -> AsyncIterator[list[Record]]:
        pg = cfg.pagination
        offset = 0
        previous: list[str] | None = None
        for _ in range(pg.max_pages):
            query = {**params, pg.offset_param: offset, pg.limit_param: size}
            records, body = await self._fetch_page(cfg, spec, query)
            if not records:
                return
            previous = _check_not_repeated(cfg, records, previous)
            yield records
            offset += len(records)
            total = dig(body, pg.total_path)
            if isinstance(total, int):
                if offset >= total:
                    return
            elif len(records) < size:
                return
        raise _exceeded(cfg)

    async def _cursor_strategy(
        self, cfg: ResourceConfig, spec: EndpointSpec, params: dict[str, Any], size: int
    ) -> AsyncIterator[list[Record]]:
        pg = cfg.pagination
        cursor: str | None = None
        seen_cursors: set[str] = set()
        for _ in range(pg.max_pages):
            query = {**params, pg.limit_param: size}
            if cursor is not None:
                query[pg.cursor_param] = cursor
            records, body = await self._fetch_page(cfg, spec, query)
            if not records:
                return
            yield records
            nxt = dig(body, pg.next_cursor_path)
            if nxt is MISSING or nxt in (None, ""):
                return
            cursor = str(nxt)
            if cursor in seen_cursors:
                raise RemoteUnavailable(f"{cfg.name}: the server repeated cursor {cursor!r}")
            seen_cursors.add(cursor)
        raise _exceeded(cfg)


def _first_int(body: Any, paths: tuple[str | None, ...]) -> int | None:
    for path in paths:
        if path is None:
            continue
        value = dig(body, path)
        if isinstance(value, int) and not isinstance(value, bool):
            return value
    return None


def _check_not_repeated(
    cfg: ResourceConfig, records: list[Record], previous: list[str] | None
) -> list[str]:
    """Loop guard of the page/offset strategies: a server that ignores the paging parameters
    answers the same page forever."""
    current = [r.id if r.id is not None else repr(dict(r.fields)) for r in records]
    if current == previous:
        raise RemoteUnavailable(
            f"{cfg.name}: the server repeated the same page; it ignores the paging parameters"
        )
    return current


def _exceeded(cfg: ResourceConfig) -> RemoteUnavailable:
    return RemoteUnavailable(
        f"{cfg.name}: pagination exceeded max_pages={cfg.pagination.max_pages}"
    )


def _filter_params(cfg: ResourceConfig, flt: RecordFilter) -> tuple[dict[str, Any], dict[str, Any]]:
    """Query parameters for the server and the equality checks left for the client."""
    params: dict[str, Any] = {}
    local: dict[str, Any] = {}
    for name, value in flt.equals.items():
        if name in cfg.filter_param_map:
            params[cfg.filter_param_map[name]] = value
        else:
            local[name] = value
    if flt.since is not None and cfg.since_param:
        params[cfg.since_param] = _iso(flt.since)
    params.update(flt.raw or {})
    return params, local


def _iso(value: datetime) -> str:
    return value.isoformat()


def _matches(record: Record, equals: Mapping[str, Any]) -> bool:
    return all(_same(record.get(name), value) for name, value in equals.items())


def _same(actual: Any, expected: Any) -> bool:
    return actual == expected or (
        actual is not None and expected is not None and str(actual) == str(expected)
    )


def _require(spec: EndpointSpec | None, cfg: ResourceConfig, operation: str) -> EndpointSpec:
    if spec is None:
        raise RecordRejected(f"resource {cfg.name!r} does not support {operation}")
    return spec


def _path(spec: EndpointSpec, id: str | None) -> str:
    return spec.path.replace("{id}", quote(id, safe="") if id is not None else "")


def _body(response: Any) -> Any:
    try:
        return response.json()
    except ValueError:
        raise RemoteUnavailable("the server answered with a body that is not JSON") from None


def _record(cfg: ResourceConfig, item: Any, fallback_id: str | None) -> Record:
    if not isinstance(item, dict):
        raise RemoteUnavailable(f"{cfg.name}: expected a JSON object for a record")
    raw_id = item.get(cfg.id_field)
    return Record(str(raw_id) if raw_id is not None else fallback_id, item)


def _written(
    cfg: ResourceConfig, content: bytes, response: Any, sent: dict[str, Any], id: str | None
) -> Record:
    if not content.strip():
        return Record(id, sent)
    return _record(cfg, dig(_body(response), cfg.item_path), id)


def _infer_fields(sample: Record) -> tuple[FieldSpec, ...]:
    return tuple(FieldSpec(name, _infer_type(value)) for name, value in sample.fields.items())


def _infer_type(value: Any) -> FieldType:
    if isinstance(value, bool):
        return FieldType.BOOLEAN
    if isinstance(value, int):
        return FieldType.INTEGER
    if isinstance(value, float):
        return FieldType.NUMBER
    if isinstance(value, str):
        if _DATE.match(value):
            return FieldType.DATE
        return FieldType.DATETIME if _DATETIME.match(value) else FieldType.STRING
    if isinstance(value, dict):
        return FieldType.OBJECT
    if isinstance(value, list):
        return FieldType.ARRAY
    return FieldType.UNKNOWN
