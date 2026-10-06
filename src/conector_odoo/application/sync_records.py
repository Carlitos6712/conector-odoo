"""Pieces of single-record sync shared by ``SyncRunner`` (whole passes) and ``RecordPropagator``
(write-through of one edited record), so both compute hashes, keys and xrefs the same way."""

import hashlib
import json
from datetime import datetime
from typing import Any

from conector_odoo.domain.errors import MappingNotFound
from conector_odoo.domain.mapping import MappingDefinition
from conector_odoo.domain.mapping_engine import apply_mapping
from conector_odoo.domain.ports import MappingRepository, RecordSink
from conector_odoo.domain.records import Record
from conector_odoo.domain.sync import MappingRef, SyncJob
from conector_odoo.domain.sync_runs import XRef


def content_hash(fields: dict[str, Any]) -> str:
    canonical = json.dumps(fields, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode()).hexdigest()


async def load_mapping(mappings: MappingRepository, ref: MappingRef) -> MappingDefinition:
    stored = await mappings.get(ref.name, ref.version)
    if stored is None:
        raise MappingNotFound(f"mapping {ref.name!r} (version {ref.version}) not found")
    return stored.definition


def create_key(job_id: int | None, forward: bool, source_id: str, digest: str) -> str:
    """Idempotency key of a record created by ``job_id``; the reverse pass is marked ``rev:``."""
    marker = "" if forward else "rev:"
    return f"sync:{job_id}:{marker}{source_id}:{digest}"


async def find_adoptable(
    job: SyncJob, dst: RecordSink, dst_resource: str, fields: dict[str, Any]
) -> str | None:
    """Id of an existing destination record matching the job's ``field:<name>`` key."""
    key_field = job.key_field
    if key_field is None:
        return None
    value = Record(None, fields).get(key_field)
    if value is None:
        return None
    found = await dst.find_by(dst_resource, key_field, value)
    return None if found is None else found.id


def build_xref(
    job: SyncJob,
    *,
    forward: bool,
    source_id: str,
    written: Record,
    digest: str,
    other_mapping: MappingDefinition | None,
    synced_at: datetime,
) -> XRef:
    """The xref of a pair after ``written`` was stored on the destination of a pass.

    Both hashes are kept: ``digest`` for the pass that moved the data, and the opposite one
    computed from the record just written, which is what makes the opposite pass treat that
    record as unchanged (echo prevention)."""
    other = None
    if other_mapping is not None:
        other = content_hash(apply_mapping(other_mapping, written).fields)
    written_id = written.id or ""
    return XRef(
        job_id=job.id or 0,
        resource=job.source.resource,
        source_id=source_id if forward else written_id,
        target_id=written_id if forward else source_id,
        content_hash=digest if forward else other,
        reverse_hash=other if forward else digest,
        synced_at=synced_at,
    )
