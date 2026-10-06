"""Turn an OpenAPI 3.x / Swagger 2.0 document into prefilled ``ResourceConfig`` candidates.

Heuristics (all best effort; anything unclear becomes a warning, never an error):

- a path without placeholders is a *collection* (``/clients``) and ``<collection>/{param}`` is its
  *item*; both are grouped into one resource;
- list = GET collection, create = POST collection, get = GET item, update = PATCH (else PUT) item;
- items path, id field, schema fields and pagination are read from the response schema and the
  query parameters of the list operation.

Paths with several placeholders, placeholders in the middle, and literal siblings of an item
template (``/clients/options`` next to ``/clients/{id}``) are reported and skipped.
"""

import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlsplit

from conector_odoo.domain.errors import ResourceConfigInvalid
from conector_odoo.domain.outbound import DEFAULT_POLICY, OutboundPolicy
from conector_odoo.domain.resource_codec import validate_resource_config
from conector_odoo.domain.resources import (
    EndpointSpec,
    PaginationConfig,
    PaginationStrategy,
    ResourceConfig,
)
from conector_odoo.infrastructure.openapi.loader import MAX_BYTES, fetch_document, load_document
from conector_odoo.infrastructure.openapi.schemas import SpecReader

_PARAM = re.compile(r"^\{[^{}]+\}$")
_SIZE_PARAMS = ("page_size", "per_page", "size", "limit", "pagesize", "page_length")
_CURSOR_PARAMS = ("cursor", "next", "after", "page_token", "next_token", "starting_after")
_CURSOR_LIMITS = ("limit", "page_size", "per_page", "size")
_NEXT_PATHS = (
    "next_cursor",
    "nextCursor",
    "next",
    "next_page_token",
    "nextPageToken",
    "next_token",
    "nextToken",
    "cursor",
)
_TOTAL_PAGES = ("total_pages", "totalPages", "pages", "page_count", "pageCount")
_TOTALS = ("total", "count", "total_count", "totalCount")
_SINCE = (
    "updated_since",
    "modified_since",
    "since",
    "updated_after",
    "modified_after",
    "changed_since",
)
_METHODS = ("get", "post", "put", "patch", "delete")


@dataclass(frozen=True, slots=True)
class ImportReport:
    candidates: tuple[ResourceConfig, ...]
    warnings: tuple[str, ...]
    base_path: str = ""


@dataclass
class _Group:
    collection: dict[str, Any] = field(default_factory=dict)  # method -> operation
    collection_params: list[dict[str, Any]] = field(default_factory=list)
    item: dict[str, Any] = field(default_factory=dict)
    item_param: str | None = None
    item_template: str = ""


class OpenApiImporter:
    def __init__(
        self, *, max_bytes: int = MAX_BYTES, policy: OutboundPolicy = DEFAULT_POLICY
    ) -> None:
        self._max_bytes = max_bytes
        self._policy = policy

    async def import_url(
        self,
        url: str,
        *,
        tls_verify: bool = True,
        headers: Mapping[str, str] | None = None,
        base_path: str | None = None,
    ) -> ImportReport:
        """Fetch ``url`` (http/https) and import it. ``tls_verify`` and ``headers`` are the
        caller's choice (e.g. a profile's); nothing is sent that is not passed."""
        content = await fetch_document(
            url,
            tls_verify=tls_verify,
            headers=headers,
            max_bytes=self._max_bytes,
            policy=self._policy,
        )
        return self.parse(content, base_path=base_path)

    def parse(self, content: bytes | str, *, base_path: str | None = None) -> ImportReport:
        """``base_path`` (e.g. the path of the profile base URL) overrides ``servers[0].url`` /
        ``basePath`` as the prefix removed from every path."""
        document = load_document(content, max_bytes=self._max_bytes)
        reader = SpecReader(document)
        base = _clean_base(base_path) if base_path is not None else _spec_base(document)
        warnings: list[str] = []
        paths = document.get("paths")
        if not isinstance(paths, dict) or not paths:
            return ImportReport((), ("the document defines no paths",), base)
        groups = self._group(reader, paths, base, warnings)
        names: set[str] = set()
        candidates: list[ResourceConfig] = []
        for collection, group in groups.items():
            config = self._build(reader, collection, group, names, warnings)
            if config is not None:
                candidates.append(config)
        return ImportReport(tuple(candidates), tuple(warnings), base)

    # -- grouping ------------------------------------------------------------------------------

    def _group(
        self, reader: SpecReader, paths: dict[str, Any], base: str, warnings: list[str]
    ) -> dict[str, _Group]:
        groups: dict[str, _Group] = {}
        item_parents: set[str] = set()
        entries: list[tuple[str, dict[str, Any]]] = []
        for raw_path, raw_item in paths.items():
            path = _strip_base(str(raw_path), base, warnings)
            path_item = reader.deref(raw_item)
            if path is not None and isinstance(path_item, dict):
                entries.append((path, path_item))
        for path, path_item in entries:
            segments = path.strip("/").split("/") if path.strip("/") else []
            params = [i for i, s in enumerate(segments) if _PARAM.match(s)]
            ops = {m: path_item[m] for m in _METHODS if isinstance(path_item.get(m), dict)}
            if not segments:
                warnings.append(f"{path}: the root path is not a resource, skipped")
            elif not params:
                group = groups.setdefault(path, _Group())
                for method, op in ops.items():
                    group.collection.setdefault(method, op)
                group.collection_params.extend(reader.parameters(path_item))
            elif params == [len(segments) - 1] and len(segments) > 1:
                parent = "/" + "/".join(segments[:-1])
                group = groups.setdefault(parent, _Group())
                item_parents.add(parent)
                group.item_param = group.item_param or segments[-1][1:-1]
                group.item_template = group.item_template or path
                for method, op in ops.items():
                    group.item.setdefault(method, op)
            else:
                warnings.append(f"{path}: nested or unsupported path template, skipped")
        return self._drop_item_siblings(groups, item_parents, warnings)

    def _drop_item_siblings(
        self, groups: dict[str, _Group], item_parents: set[str], warnings: list[str]
    ) -> dict[str, _Group]:
        kept: dict[str, _Group] = {}
        for path, group in groups.items():
            parent = path.rsplit("/", 1)[0]
            if group.collection and not group.item and parent in item_parents:
                warnings.append(
                    f"{path}: looks like an action or sub-resource of {parent}/{{...}}, skipped"
                )
            else:
                kept[path] = group
        return kept

    # -- one resource ----------------------------------------------------------------------------

    def _build(
        self,
        reader: SpecReader,
        collection: str,
        group: _Group,
        names: set[str],
        warnings: list[str],
    ) -> ResourceConfig | None:
        list_op = group.collection.get("get")
        create_op = group.collection.get("post")
        get_op = group.item.get("get")
        update_method = next((m for m in ("patch", "put") if m in group.item), None)
        if not (list_op or create_op or get_op or update_method):
            where = group.item_template or collection
            warnings.append(f"{where}: no list, get, create or update operation, skipped")
            return None
        name = _unique_name(collection, names)
        notes: list[str] = []

        items_path = ""
        item_schema: dict[str, Any] = {}
        root_props: dict[str, Any] = {}
        if list_op is not None:
            shape = reader.list_shape(reader.response_schema(list_op))
            if shape is None:
                notes.append("the list response has no usable schema, items_path left empty")
            else:
                items_path, item_schema, root_props = shape
        item_path = ""
        if get_op is not None:
            item_path, get_schema = reader.item_shape(reader.response_schema(get_op))
            if get_schema.get("properties"):
                item_schema = get_schema
        fields = reader.fields(item_schema)
        id_field = _id_field(collection, group.item_param, {f.name for f in fields})
        if not fields:
            notes.append(f"no record schema found, id_field assumed to be {id_field!r}")

        params = reader.parameters({"parameters": group.collection_params}, list_op or {})
        pagination = _pagination(params, root_props, notes)
        used = {p["name"] for p in params if p.get("in") == "query"}
        paging = {
            pagination.page_param,
            pagination.size_param,
            pagination.offset_param,
            pagination.limit_param,
            pagination.cursor_param,
        }
        since = next((n for n in used if n.lower() in _SINCE), None)
        names_in_schema = {f.name for f in fields}
        filters = {n: n for n in sorted(used) if n in names_in_schema and n not in paging}

        config = ResourceConfig(
            name=name,
            label=_label(collection),
            list_endpoint=EndpointSpec("GET", collection) if list_op is not None else None,
            get_endpoint=EndpointSpec("GET", f"{collection}/{{id}}")
            if get_op is not None
            else None,
            create_endpoint=EndpointSpec("POST", collection) if create_op is not None else None,
            update_endpoint=(
                EndpointSpec(update_method.upper(), f"{collection}/{{id}}")
                if update_method
                else None
            ),
            items_path=items_path,
            item_path=item_path,
            id_field=id_field,
            pagination=pagination,
            filter_param_map=filters,
            since_param=since,
            schema_fields=fields,
        )
        try:
            validate_resource_config(config)
        except ResourceConfigInvalid as exc:
            warnings.append(f"{collection}: generated configuration is invalid ({exc}), skipped")
            return None
        warnings.extend(f"{name}: {note}" for note in notes)
        return config


# -- helpers ---------------------------------------------------------------------------------------


def _clean_base(value: str) -> str:
    stripped = value.strip().strip("/")
    return f"/{stripped}" if stripped else ""


def _spec_base(document: dict[str, Any]) -> str:
    if "swagger" in document:
        base = document.get("basePath")
        return _clean_base(base) if isinstance(base, str) else ""
    servers = document.get("servers")
    if isinstance(servers, list) and servers and isinstance(servers[0], dict):
        url = servers[0].get("url")
        if isinstance(url, str):
            variables = servers[0].get("variables")
            for key, spec in (variables if isinstance(variables, dict) else {}).items():
                default = spec.get("default") if isinstance(spec, dict) else None
                url = url.replace(f"{{{key}}}", str(default if default is not None else ""))
            return _clean_base(urlsplit(url).path)
    return ""


def _strip_base(path: str, base: str, warnings: list[str]) -> str | None:
    if not path.startswith("/"):
        warnings.append(f"{path}: paths must start with '/', skipped")
        return None
    if base and (path == base or path.startswith(base + "/")):
        path = path[len(base) :] or "/"
    elif base:
        warnings.append(f"{path}: outside the base path {base}, kept as is")
    return path.rstrip("/") or "/"


def _unique_name(collection: str, taken: set[str]) -> str:
    parts = [
        re.sub(r"[^A-Za-z0-9_]+", "_", s).strip("_") or "x"
        for s in collection.strip("/").split("/")
    ]
    base = ".".join(parts)
    name, n = base, 1
    while name in taken:
        n += 1
        name = f"{base}_{n}"
    taken.add(name)
    return name


def _label(collection: str) -> str:
    last = collection.rstrip("/").rsplit("/", 1)[-1]
    return re.sub(r"[-_]+", " ", last).strip().title() or collection


def _singular(collection: str) -> str:
    word = (
        re.sub(r"[^A-Za-z0-9]+", "_", collection.rstrip("/").rsplit("/", 1)[-1]).strip("_").lower()
    )
    if word.endswith("ies") and len(word) > 3:
        return word[:-3] + "y"
    return word[:-1] if word.endswith("s") and not word.endswith("ss") else word


def _id_field(collection: str, param: str | None, props: set[str]) -> str:
    if not props:
        return "id"
    for candidate in ("id", "uuid", f"{_singular(collection)}_id", param):
        if candidate and candidate in props:
            return candidate
    return param or "id"


def _pagination(
    params: list[dict[str, Any]], root_props: Mapping[str, Any], notes: list[str]
) -> PaginationConfig:
    names = {str(p["name"]).lower(): str(p["name"]) for p in params if p.get("in") == "query"}

    def pick(options: tuple[str, ...]) -> str | None:
        return next((names[o] for o in options if o in names), None)

    def root(options: tuple[str, ...]) -> str | None:
        return next((o for o in options if o in root_props), None)

    size, page = pick(_SIZE_PARAMS), names.get("page")
    if page and size:
        return PaginationConfig(
            PaginationStrategy.PAGE,
            page_param=page,
            size_param=size,
            total_pages_path=root(_TOTAL_PAGES),
        )
    if "offset" in names and "limit" in names:
        return PaginationConfig(
            PaginationStrategy.OFFSET,
            offset_param=names["offset"],
            limit_param=names["limit"],
            total_path=root(_TOTALS),
        )
    cursor = pick(_CURSOR_PARAMS)
    if cursor:
        next_path = root(_NEXT_PATHS)
        if next_path is None:
            notes.append("cursor pagination detected but next_cursor_path is a guess, set it")
        return PaginationConfig(
            PaginationStrategy.CURSOR,
            cursor_param=cursor,
            limit_param=pick(_CURSOR_LIMITS) or "limit",
            next_cursor_path=next_path or "next_cursor",
        )
    return PaginationConfig()
