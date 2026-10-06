from typing import Any

from conector_odoo.domain.records import RecordFilter
from conector_odoo.domain.sync import (
    ConflictRule,
    Direction,
    EndpointRef,
    ManualTrigger,
    MappingRef,
    SyncJob,
)


def make_job(
    *,
    id: int | None = None,
    name: str = "customers",
    source_profile: int = 1,
    target_profile: int = 2,
    direction: Direction = Direction.A_TO_B,
    upsert_key: str = "xref",
    conflict_rule: ConflictRule = ConflictRule.SOURCE_WINS,
    **overrides: Any,
) -> SyncJob:
    values: dict[str, Any] = {
        "id": id,
        "name": name,
        "source": EndpointRef(source_profile, "customers"),
        "target": EndpointRef(target_profile, "clients"),
        "mapping": MappingRef("fwd"),
        "reverse_mapping": MappingRef("rev") if direction is not Direction.A_TO_B else None,
        "direction": direction,
        "trigger": ManualTrigger(),
        "record_filter": RecordFilter(),
        "batch_size": 100,
        "upsert_key": upsert_key,
        "conflict_rule": conflict_rule,
        "enabled": True,
    }
    values.update(overrides)
    return SyncJob(**values)
