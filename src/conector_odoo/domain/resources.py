"""Description of a remote REST resource: where its endpoints are and how it paginates.

Pure domain: stdlib only. B6 will persist/import these; adapters receive them through the
``ResourceConfigProvider`` port and never know where they are stored.
"""

from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum

from conector_odoo.domain.records import FieldSpec


class PaginationStrategy(StrEnum):
    NONE = "none"
    PAGE = "page"
    OFFSET = "offset"
    CURSOR = "cursor"


@dataclass(frozen=True, slots=True)
class EndpointSpec:
    """HTTP method plus a path template; ``{id}`` is replaced by the (URL-quoted) record id."""

    method: str
    path: str


@dataclass(frozen=True, slots=True)
class PaginationConfig:
    """Parameters per strategy; ``*_path`` values are dotted JSON paths into the list response.

    ``max_pages`` bounds a walk so a server that ignores the paging parameters cannot loop forever.
    """

    strategy: PaginationStrategy = PaginationStrategy.NONE
    # PAGE
    page_param: str = "page"
    size_param: str = "page_size"
    first_page: int = 1
    total_pages_path: str | None = None
    # OFFSET (also uses ``total_path``)
    offset_param: str = "offset"
    limit_param: str = "limit"
    total_path: str | None = None
    # CURSOR (also uses ``limit_param``)
    cursor_param: str = "cursor"
    next_cursor_path: str | None = None
    max_pages: int = 10_000


@dataclass(frozen=True, slots=True)
class ResourceConfig:
    """One REST resource. Missing endpoint specs mean the operation is not supported.

    ``items_path`` locates the list inside a list response (empty = the body is the array);
    ``item_path`` locates the record inside a single-record response (empty = the whole body).
    ``filter_param_map`` maps a record field to the query parameter that filters on it and
    ``since_param`` is the parameter for a modification-time lower bound.
    """

    name: str
    label: str
    list_endpoint: EndpointSpec | None = None
    get_endpoint: EndpointSpec | None = None
    create_endpoint: EndpointSpec | None = None
    update_endpoint: EndpointSpec | None = None
    items_path: str = ""
    item_path: str = ""
    id_field: str = "id"
    pagination: PaginationConfig = field(default_factory=PaginationConfig)
    filter_param_map: Mapping[str, str] = field(default_factory=dict)
    since_param: str | None = None
    schema_fields: tuple[FieldSpec, ...] = ()
