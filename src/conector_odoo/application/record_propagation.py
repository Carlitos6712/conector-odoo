"""Write-through of one record to its counterpart in a bidirectional sync.

When a record is created, edited or deleted from the connector, the same change is applied to the
paired record of every enabled ``bidirectional`` job (with a reverse mapping) that links it, using
the job's xref. The edited side always wins: this is an explicit user action, so the job's
conflict rule is not consulted.

* Side A of a job uses the forward mapping to build the fields of side B; side B uses the reverse
  mapping to build side A. A mapped record equal to what the xref stored for that side (nothing
  to change) is skipped.
* After a successful counterpart write the xref is stored with BOTH hashes recomputed exactly as
  the sync runner does (``build_xref``), so the next job run sees both sides as unchanged.
* A counterpart that fails never raises: the outcome carries a warning and the xref is left
  untouched (stale), so the next job run reconciles. Deleting a counterpart that is already gone
  is a success; one that refuses the deletion keeps its xref (the pair stays linked).

Every method returns one ``PropagationOutcome`` per job side that matched.
"""

import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime

from conector_odoo.application.sync_records import (
    build_xref,
    content_hash,
    create_key,
    find_adoptable,
    load_mapping,
)
from conector_odoo.domain.errors import ConnectorError, ResourceNotFound
from conector_odoo.domain.mapping import MappingDefinition
from conector_odoo.domain.mapping_engine import apply_mapping
from conector_odoo.domain.ports import (
    MappingRepository,
    RecordEndpoint,
    SyncJobRepository,
    XRefRepository,
)
from conector_odoo.domain.records import Record
from conector_odoo.domain.sync import Direction, SyncJob
from conector_odoo.domain.sync_runs import Side, XRef

logger = logging.getLogger(__name__)

EndpointProvider = Callable[[int], Awaitable[RecordEndpoint]]
Clock = Callable[[], datetime]


@dataclass(frozen=True, slots=True)
class PropagationOutcome:
    """What happened to the counterpart of the edited record for one job.

    ``side`` is the side of the EDITED record (``SOURCE`` = A, ``TARGET`` = B); ``action`` is
    ``updated``, ``created``, ``deleted``, ``skipped`` (nothing to do) or ``failed`` (see
    ``warning``)."""

    job_id: int | None
    job_name: str
    side: Side
    action: str
    counterpart_id: str | None = None
    warning: str | None = None


@dataclass(frozen=True, slots=True)
class _Leg:
    """One job seen from the side of the edited record."""

    job: SyncJob
    forward: bool  # the edited record is on side A
    mapping: MappingDefinition
    other_mapping: MappingDefinition
    dst: RecordEndpoint
    dst_resource: str

    @property
    def side(self) -> Side:
        return Side.SOURCE if self.forward else Side.TARGET


class RecordPropagator:
    def __init__(
        self,
        jobs: SyncJobRepository,
        mappings: MappingRepository,
        xrefs: XRefRepository,
        endpoints: EndpointProvider,
        *,
        clock: Clock = lambda: datetime.now(UTC),
    ) -> None:
        self._jobs = jobs
        self._mappings = mappings
        self._xrefs = xrefs
        self._endpoints = endpoints
        self._clock = clock

    async def propagate_update(
        self, profile_id: int, resource: str, record_id: str, written_record: Record
    ) -> list[PropagationOutcome]:
        """Apply an edit; a record with no xref in a job is skipped for that job."""
        return await self._each(
            profile_id,
            resource,
            lambda leg: self._upsert(leg, record_id, written_record, link_missing=False),
        )

    async def propagate_create(
        self, profile_id: int, resource: str, written_record: Record
    ) -> list[PropagationOutcome]:
        """Apply a new record: create the counterpart (or adopt a ``field:<key>`` match) and link
        them. A record that already has an xref in a job is treated as an edit."""
        record_id = written_record.id or ""
        return await self._each(
            profile_id,
            resource,
            lambda leg: self._upsert(leg, record_id, written_record, link_missing=True),
        )

    async def propagate_delete(
        self, profile_id: int, resource: str, record_id: str
    ) -> list[PropagationOutcome]:
        return await self._each(profile_id, resource, lambda leg: self._delete(leg, record_id))

    # -- orchestration ---------------------------------------------------------------------

    async def _each(
        self,
        profile_id: int,
        resource: str,
        action: Callable[[_Leg], Awaitable[PropagationOutcome]],
    ) -> list[PropagationOutcome]:
        outcomes: list[PropagationOutcome] = []
        for job in await self._jobs.list():
            if not _takes_part(job):
                continue
            for forward in (True, False):
                end = job.source if forward else job.target
                if (end.profile_id, end.resource) != (profile_id, resource):
                    continue
                try:
                    outcome = await action(await self._leg(job, forward))
                except Exception as exc:  # a counterpart problem never fails the primary write
                    logger.exception("write-through failed for job %s", job.id)
                    outcomes.append(
                        PropagationOutcome(
                            job.id,
                            job.name,
                            Side.SOURCE if forward else Side.TARGET,
                            "failed",
                            warning=str(exc) if isinstance(exc, ConnectorError) else _GENERIC,
                        )
                    )
                else:
                    outcomes.append(outcome)
        return outcomes

    async def _leg(self, job: SyncJob, forward: bool) -> _Leg:
        assert job.reverse_mapping is not None  # _takes_part
        forward_map = await load_mapping(self._mappings, job.mapping)
        reverse_map = await load_mapping(self._mappings, job.reverse_mapping)
        target = job.target if forward else job.source
        return _Leg(
            job,
            forward,
            forward_map if forward else reverse_map,
            reverse_map if forward else forward_map,
            await self._endpoints(target.profile_id),
            target.resource,
        )

    async def _xref(self, leg: _Leg, record_id: str) -> XRef | None:
        job, resource = leg.job, leg.job.source.resource
        if leg.forward:
            return await self._xrefs.get_target(job.id or 0, resource, record_id)
        return await self._xrefs.get_source(job.id or 0, resource, record_id)

    # -- write ---------------------------------------------------------------------------------

    async def _upsert(
        self, leg: _Leg, record_id: str, written: Record, *, link_missing: bool
    ) -> PropagationOutcome:
        mapped = apply_mapping(leg.mapping, written)
        if mapped.errors:
            detail = "; ".join(f"{e.rule_target}: {e.message}" for e in mapped.errors)
            return self._outcome(leg, "failed", warning=f"mapping failed: {detail}")
        fields, digest = mapped.fields, content_hash(mapped.fields)
        xref = await self._xref(leg, record_id)
        if xref is not None:
            if (xref.content_hash if leg.forward else xref.reverse_hash) == digest:
                return self._outcome(leg, "skipped", _counterpart_id(leg, xref))
            target_id: str | None = _counterpart_id(leg, xref)
        elif link_missing:
            target_id = await find_adoptable(leg.job, leg.dst, leg.dst_resource, fields)
        else:
            return self._outcome(leg, "skipped")
        counterpart: Record | None = None
        action = "updated"
        if target_id is not None:
            try:
                counterpart = await leg.dst.update(leg.dst_resource, target_id, fields)
            except ResourceNotFound:
                action = "created"  # the paired record was deleted there: recreate it
        if counterpart is None:
            action = "created"
            key = create_key(leg.job.id, leg.forward, record_id, digest)
            counterpart = await leg.dst.create(leg.dst_resource, fields, key)
        await self._xrefs.upsert(
            build_xref(
                leg.job,
                forward=leg.forward,
                source_id=record_id,
                written=counterpart,
                digest=digest,
                other_mapping=leg.other_mapping,
                synced_at=self._clock(),
            )
        )
        return self._outcome(leg, action, counterpart.id)

    async def _delete(self, leg: _Leg, record_id: str) -> PropagationOutcome:
        xref = await self._xref(leg, record_id)
        if xref is None:
            return self._outcome(leg, "skipped")
        counterpart_id = _counterpart_id(leg, xref)
        try:
            await leg.dst.delete(leg.dst_resource, counterpart_id)
        except ResourceNotFound:
            pass  # already gone: the goal is met
        except ConnectorError as exc:  # refused or unreachable: keep the pair linked
            return self._outcome(leg, "failed", counterpart_id, warning=str(exc))
        await self._xrefs.forget(leg.job.id or 0, leg.job.source.resource, xref.source_id)
        return self._outcome(leg, "deleted", counterpart_id)

    @staticmethod
    def _outcome(
        leg: _Leg, action: str, counterpart_id: str | None = None, *, warning: str | None = None
    ) -> PropagationOutcome:
        return PropagationOutcome(
            leg.job.id, leg.job.name, leg.side, action, counterpart_id, warning
        )


_GENERIC = "the counterpart could not be updated"


def _takes_part(job: SyncJob) -> bool:
    return (
        job.enabled and job.direction is Direction.BIDIRECTIONAL and job.reverse_mapping is not None
    )


def _counterpart_id(leg: _Leg, xref: XRef) -> str:
    return xref.target_id if leg.forward else xref.source_id
