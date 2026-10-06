from datetime import datetime
from typing import Annotated, Any, Literal, Self

from pydantic import BaseModel, Field

from conector_odoo.domain.records import RecordFilter
from conector_odoo.domain.sync import (
    ConflictRule,
    Direction,
    EndpointRef,
    ManualTrigger,
    MappingRef,
    ScheduleTrigger,
    SyncJob,
    Trigger,
    WebhookTrigger,
)
from conector_odoo.infrastructure.admin_api.schemas.common import StrictModel


class EndpointRefModel(StrictModel):
    profile_id: int = Field(gt=0)
    resource: str = Field(min_length=1)


class MappingRefModel(StrictModel):
    name: str = Field(min_length=1)
    version: int | None = Field(default=None, ge=1)


class ManualTriggerModel(StrictModel):
    kind: Literal["manual"]


class ScheduleTriggerModel(StrictModel):
    kind: Literal["schedule"]
    cron: str


class WebhookTriggerModel(StrictModel):
    kind: Literal["webhook"]
    event_types: list[str]


TriggerModel = Annotated[
    ManualTriggerModel | ScheduleTriggerModel | WebhookTriggerModel, Field(discriminator="kind")
]


class RecordFilterModel(StrictModel):
    equals: dict[str, Any] = Field(default_factory=dict)
    since: datetime | None = None
    raw: dict[str, Any] | None = None


class JobIn(StrictModel):
    name: str = Field(min_length=1, max_length=120)
    source: EndpointRefModel
    target: EndpointRefModel
    mapping: MappingRefModel
    reverse_mapping: MappingRefModel | None = None
    direction: Direction = Direction.A_TO_B
    trigger: TriggerModel = Field(default_factory=lambda: ManualTriggerModel(kind="manual"))
    record_filter: RecordFilterModel = Field(default_factory=RecordFilterModel)
    reverse_record_filter: RecordFilterModel = Field(default_factory=RecordFilterModel)
    batch_size: int = 100
    upsert_key: str = "xref"
    conflict_rule: ConflictRule = ConflictRule.SOURCE_WINS
    source_updated_field: str | None = None
    target_updated_field: str | None = None
    enabled: bool = True

    def to_domain(self) -> SyncJob:
        trigger: Trigger
        if isinstance(self.trigger, ScheduleTriggerModel):
            trigger = ScheduleTrigger(self.trigger.cron)
        elif isinstance(self.trigger, WebhookTriggerModel):
            trigger = WebhookTrigger(tuple(self.trigger.event_types))
        else:
            trigger = ManualTrigger()
        reverse = self.reverse_mapping
        return SyncJob(
            id=None,
            name=self.name,
            source=EndpointRef(self.source.profile_id, self.source.resource),
            target=EndpointRef(self.target.profile_id, self.target.resource),
            mapping=MappingRef(self.mapping.name, self.mapping.version),
            reverse_mapping=None if reverse is None else MappingRef(reverse.name, reverse.version),
            direction=self.direction,
            trigger=trigger,
            record_filter=RecordFilter(
                equals=dict(self.record_filter.equals),
                since=self.record_filter.since,
                raw=self.record_filter.raw,
            ),
            reverse_record_filter=RecordFilter(
                equals=dict(self.reverse_record_filter.equals),
                since=self.reverse_record_filter.since,
                raw=self.reverse_record_filter.raw,
            ),
            batch_size=self.batch_size,
            upsert_key=self.upsert_key,
            conflict_rule=self.conflict_rule,
            source_updated_field=self.source_updated_field,
            target_updated_field=self.target_updated_field,
            enabled=self.enabled,
        )


class JobOut(JobIn):
    id: int
    next_fire: datetime | None = None

    @classmethod
    def of(cls, job: SyncJob, next_fire: datetime | None = None) -> Self:
        assert job.id is not None
        trigger: ManualTriggerModel | ScheduleTriggerModel | WebhookTriggerModel
        if isinstance(job.trigger, ScheduleTrigger):
            trigger = ScheduleTriggerModel(kind="schedule", cron=job.trigger.cron)
        elif isinstance(job.trigger, WebhookTrigger):
            trigger = WebhookTriggerModel(kind="webhook", event_types=list(job.trigger.event_types))
        else:
            trigger = ManualTriggerModel(kind="manual")
        reverse = job.reverse_mapping
        return cls(
            id=job.id,
            name=job.name,
            source=EndpointRefModel(profile_id=job.source.profile_id, resource=job.source.resource),
            target=EndpointRefModel(profile_id=job.target.profile_id, resource=job.target.resource),
            mapping=MappingRefModel(name=job.mapping.name, version=job.mapping.version),
            reverse_mapping=None
            if reverse is None
            else MappingRefModel(name=reverse.name, version=reverse.version),
            direction=job.direction,
            trigger=trigger,
            record_filter=RecordFilterModel(
                equals=dict(job.record_filter.equals),
                since=job.record_filter.since,
                raw=None if job.record_filter.raw is None else dict(job.record_filter.raw),
            ),
            reverse_record_filter=RecordFilterModel(
                equals=dict(job.reverse_record_filter.equals),
                since=job.reverse_record_filter.since,
                raw=(
                    None
                    if job.reverse_record_filter.raw is None
                    else dict(job.reverse_record_filter.raw)
                ),
            ),
            batch_size=job.batch_size,
            upsert_key=job.upsert_key,
            conflict_rule=job.conflict_rule,
            source_updated_field=job.source_updated_field,
            target_updated_field=job.target_updated_field,
            enabled=job.enabled,
            next_fire=next_fire,
        )


class JobListOut(BaseModel):
    items: list[JobOut]


class TriggerRunIn(StrictModel):
    dry_run: bool = False
    only_records: list[str] | None = None
