from datetime import datetime
from typing import Self

from pydantic import BaseModel, Field, model_validator

from conector_odoo.application.resources import DiscoveredResource, PreviewResult
from conector_odoo.domain.records import FieldSpec, FieldType, Record, ResourceSchema
from conector_odoo.domain.resources import (
    CatalogListing,
    EndpointSpec,
    PaginationConfig,
    PaginationStrategy,
    ResourceConfig,
    ResourceSource,
    StoredResource,
)
from conector_odoo.infrastructure.admin_api.schemas.common import StrictModel
from conector_odoo.infrastructure.openapi.importer import ImportReport


class EndpointModel(StrictModel):
    method: str
    path: str


class PaginationModel(StrictModel):
    strategy: PaginationStrategy = PaginationStrategy.NONE
    page_param: str = "page"
    size_param: str = "page_size"
    first_page: int = 1
    total_pages_path: str | None = None
    offset_param: str = "offset"
    limit_param: str = "limit"
    total_path: str | None = None
    cursor_param: str = "cursor"
    next_cursor_path: str | None = None
    max_pages: int = Field(default=10_000, ge=1)


class FieldModel(StrictModel):
    name: str
    type: FieldType = FieldType.UNKNOWN
    required: bool = False
    readonly: bool = False
    label: str | None = None
    choices: list[str] | None = None
    relation: str | None = None


class ResourceConfigModel(StrictModel):
    """The editable description of one REST resource (mirrors ``ResourceConfig``)."""

    name: str
    label: str = ""
    list_endpoint: EndpointModel | None = None
    get_endpoint: EndpointModel | None = None
    create_endpoint: EndpointModel | None = None
    update_endpoint: EndpointModel | None = None
    items_path: str = ""
    item_path: str = ""
    id_field: str = "id"
    pagination: PaginationModel = Field(default_factory=PaginationModel)
    filter_param_map: dict[str, str] = Field(default_factory=dict)
    since_param: str | None = None
    schema_fields: list[FieldModel] = Field(default_factory=list)

    def to_domain(self) -> ResourceConfig:
        def endpoint(model: EndpointModel | None) -> EndpointSpec | None:
            return None if model is None else EndpointSpec(model.method, model.path)

        return ResourceConfig(
            name=self.name,
            label=self.label or self.name,
            list_endpoint=endpoint(self.list_endpoint),
            get_endpoint=endpoint(self.get_endpoint),
            create_endpoint=endpoint(self.create_endpoint),
            update_endpoint=endpoint(self.update_endpoint),
            items_path=self.items_path,
            item_path=self.item_path,
            id_field=self.id_field,
            pagination=PaginationConfig(**self.pagination.model_dump()),
            filter_param_map=dict(self.filter_param_map),
            since_param=self.since_param,
            schema_fields=tuple(
                FieldSpec(
                    f.name,
                    f.type,
                    f.required,
                    f.readonly,
                    f.label,
                    None if f.choices is None else tuple(f.choices),
                    f.relation,
                )
                for f in self.schema_fields
            ),
        )

    @classmethod
    def of(cls, config: ResourceConfig) -> Self:
        def endpoint(spec: EndpointSpec | None) -> EndpointModel | None:
            return None if spec is None else EndpointModel(method=spec.method, path=spec.path)

        pg = config.pagination
        return cls(
            name=config.name,
            label=config.label,
            list_endpoint=endpoint(config.list_endpoint),
            get_endpoint=endpoint(config.get_endpoint),
            create_endpoint=endpoint(config.create_endpoint),
            update_endpoint=endpoint(config.update_endpoint),
            items_path=config.items_path,
            item_path=config.item_path,
            id_field=config.id_field,
            pagination=PaginationModel(**{k: getattr(pg, k) for k in PaginationModel.model_fields}),
            filter_param_map=dict(config.filter_param_map),
            since_param=config.since_param,
            schema_fields=[
                FieldModel(
                    name=f.name,
                    type=f.type,
                    required=f.required,
                    readonly=f.readonly,
                    label=f.label,
                    choices=None if f.choices is None else list(f.choices),
                    relation=f.relation,
                )
                for f in config.schema_fields
            ],
        )


class ResourcePutIn(ResourceConfigModel):
    """The config plus where it came from (``openapi`` when prefilled from an import)."""

    source: ResourceSource = ResourceSource.MANUAL


class StoredResourceOut(BaseModel):
    profile_id: int
    config: ResourceConfigModel
    source: ResourceSource
    updated_at: datetime

    @classmethod
    def of(cls, stored: StoredResource) -> Self:
        return cls(
            profile_id=stored.profile_id,
            config=ResourceConfigModel.of(stored.config),
            source=stored.source,
            updated_at=stored.updated_at,
        )


class ResourceProblemOut(BaseModel):
    name: str
    reason: str


class StoredResourceListOut(BaseModel):
    """``invalid`` names catalog entries that could not be read; they are skipped, not fatal."""

    items: list[StoredResourceOut]
    invalid: list[ResourceProblemOut] = Field(default_factory=list)

    @classmethod
    def of(cls, listing: CatalogListing) -> Self:
        return cls(
            items=[StoredResourceOut.of(s) for s in listing.items],
            invalid=[ResourceProblemOut(name=p.name, reason=p.reason) for p in listing.problems],
        )


class RecordOut(BaseModel):
    id: str | None
    fields: dict[str, object]

    @classmethod
    def of(cls, record: Record) -> Self:
        return cls(id=record.id, fields=dict(record.fields))


class ResourceSchemaOut(BaseModel):
    name: str
    label: str
    id_field: str
    fields: list[FieldModel]

    @classmethod
    def of(cls, schema: ResourceSchema) -> Self:
        return cls(
            name=schema.name,
            label=schema.label,
            id_field=schema.id_field,
            fields=[
                FieldModel(
                    name=f.name,
                    type=f.type,
                    required=f.required,
                    readonly=f.readonly,
                    label=f.label,
                    choices=None if f.choices is None else list(f.choices),
                    relation=f.relation,
                )
                for f in schema.fields
            ],
        )


class PreviewOut(BaseModel):
    records: list[RecordOut]
    schema_: ResourceSchemaOut = Field(serialization_alias="schema")
    warnings: list[str] = Field(default_factory=list)

    @classmethod
    def of(cls, result: PreviewResult) -> Self:
        return cls(
            records=[RecordOut.of(r) for r in result.records],
            schema_=ResourceSchemaOut.of(result.schema),
            warnings=list(result.warnings),
        )


class DiscoveredOut(BaseModel):
    name: str
    label: str


class DiscoveredListOut(BaseModel):
    items: list[DiscoveredOut]

    @classmethod
    def of(cls, found: list[DiscoveredResource]) -> Self:
        return cls(items=[DiscoveredOut(name=d.name, label=d.label) for d in found])


class OpenApiImportIn(StrictModel):
    """Exactly one of ``url`` or ``document``. ``base_path`` overrides the spec's server path."""

    url: str | None = Field(default=None, max_length=2048)
    document: str | None = None
    base_path: str | None = None

    @model_validator(mode="after")
    def _exactly_one_source(self) -> Self:
        if (self.url is None) == (self.document is None):
            raise ValueError("provide exactly one of url or document")
        return self


class ImportReportOut(BaseModel):
    candidates: list[ResourceConfigModel]
    warnings: list[str]
    base_path: str

    @classmethod
    def of(cls, report: ImportReport) -> Self:
        return cls(
            candidates=[ResourceConfigModel.of(c) for c in report.candidates],
            warnings=list(report.warnings),
            base_path=report.base_path,
        )
