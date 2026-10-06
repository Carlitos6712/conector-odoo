"""Use cases for browsing and correcting INDIVIDUAL records of a connected system.

List (text search + bounded pagination), get, edit and delete ONE record. There is deliberately
no collection-level or filter-based delete: removing many records is a backup-and-restore matter
(see the README), never a one-click operation.

Deleting a record that is the target of a sync job also forgets the cross-references pointing at
it. Otherwise an unchanged source record would keep matching its stale xref hash and the next run
would skip it forever (a changed one would be re-created, see ``SyncRunner``).

Create, edit and delete are written through to the counterpart of every enabled bidirectional job
(``RecordPropagator``). The primary write is never rolled back: a counterpart problem comes back as
a ``PropagationOutcome`` with a warning.
"""

import logging
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from conector_odoo.application.record_propagation import PropagationOutcome, RecordPropagator
from conector_odoo.domain.errors import ProfileNotFound, RecordRejected, ResourceNotFound
from conector_odoo.domain.ports import (
    ConnectionProfileRepository,
    RecordEndpoint,
    XRefRepository,
)
from conector_odoo.domain.profiles import ProfileType
from conector_odoo.domain.records import Record, RecordFilter, ResourceSchema

logger = logging.getLogger(__name__)

DEFAULT_LIMIT = 25
MAX_LIMIT = 100
MAX_OFFSET = 10_000
# Client-side text search (no server-side filter available) reads at most this many records.
MAX_SEARCH_SCAN = 5_000
_BATCH = 500

EndpointProvider = Callable[[int], Awaitable[RecordEndpoint]]


@dataclass(frozen=True, slots=True)
class RecordPage:
    items: tuple[Record, ...]
    schema: ResourceSchema
    limit: int
    offset: int
    has_more: bool


@dataclass(frozen=True, slots=True)
class RecordWrite:
    """The record as written on the targeted profile plus what happened to its counterparts."""

    record: Record
    propagation: tuple[PropagationOutcome, ...] = ()


@dataclass(frozen=True, slots=True)
class RecordDelete:
    """What a delete did: counterpart outcomes per job, and whether the record was already gone."""

    propagation: tuple[PropagationOutcome, ...] = ()
    already_deleted: bool = False


class _Base:
    def __init__(self, profiles: ConnectionProfileRepository, endpoints: EndpointProvider) -> None:
        self._profiles = profiles
        self._endpoints = endpoints

    async def _endpoint(self, profile_id: int) -> RecordEndpoint:
        # The provider caches one endpoint per profile: it is shared with the sync runner and is
        # closed by the services, never here.
        return await self._endpoints(profile_id)

    async def _profile_type(self, profile_id: int) -> ProfileType:
        stored = await self._profiles.get(profile_id)
        if stored is None:
            raise ProfileNotFound(f"connection profile {profile_id} not found")
        return stored.profile.type


class ListRecords(_Base):
    async def execute(
        self,
        profile_id: int,
        resource: str,
        *,
        search: str | None = None,
        limit: int = DEFAULT_LIMIT,
        offset: int = 0,
    ) -> RecordPage:
        """Raises ``ProfileNotFound``, ``ResourceNotFound`` and the remote errors."""
        limit = max(1, min(limit, MAX_LIMIT))
        offset = max(0, min(offset, MAX_OFFSET))
        profile_type = await self._profile_type(profile_id)
        endpoint = await self._endpoint(profile_id)
        schema = await endpoint.describe(resource)
        text = (search or "").strip()
        record_filter = RecordFilter()
        client_side = False
        if text:
            if profile_type is ProfileType.ODOO and schema.field("name") is not None:
                record_filter = RecordFilter(raw={"domain": [["name", "ilike", text]]})
            else:
                client_side = True
        items: list[Record] = []
        seen = 0
        scanned = 0
        stream = endpoint.iter_batches(resource, record_filter, _BATCH)
        done = False
        try:
            async for batch in stream:
                for record in batch:
                    scanned += 1
                    if not client_side or _matches(record, schema, text):
                        seen += 1
                        if seen > offset:
                            items.append(record)
                    # one extra record tells whether another page exists
                    if len(items) > limit or (client_side and scanned >= MAX_SEARCH_SCAN):
                        done = True
                        break
                if done:
                    break
        finally:
            aclose = getattr(stream, "aclose", None)
            if aclose is not None:
                await aclose()
        has_more = len(items) > limit
        return RecordPage(tuple(items[:limit]), schema, limit, offset, has_more)


def _matches(record: Record, schema: ResourceSchema, text: str) -> bool:
    needle = text.casefold()
    return any(
        isinstance(value, str) and needle in value.casefold()
        for name, value in record.fields.items()
        if (spec := schema.field(name)) is None or spec.type.value == "string"
    )


class GetRecord(_Base):
    async def execute(self, profile_id: int, resource: str, record_id: str) -> Record:
        """Raises ``ResourceNotFound`` when the record (or the resource) does not exist."""
        endpoint = await self._endpoint(profile_id)
        record = await endpoint.get(resource, record_id)
        if record is None:
            raise ResourceNotFound(f"{resource}: record {record_id} not found")
        return record


class CreateRecord(_Base):
    def __init__(
        self,
        profiles: ConnectionProfileRepository,
        endpoints: EndpointProvider,
        propagator: RecordPropagator,
    ) -> None:
        super().__init__(profiles, endpoints)
        self._propagator = propagator

    async def execute(self, profile_id: int, resource: str, fields: dict[str, Any]) -> RecordWrite:
        """Create ONE record, then create (or adopt) its counterpart in every bidirectional job.

        Raises ``RecordRejected`` (field errors per name) and ``ResourceNotFound``."""
        endpoint = await self._endpoint(profile_id)
        schema = await endpoint.describe(resource)
        _check_editable(schema, fields)
        created = await endpoint.create(resource, fields, uuid.uuid4().hex)
        outcomes = await self._propagator.propagate_create(profile_id, resource, created)
        return RecordWrite(created, tuple(outcomes))


class UpdateRecord(_Base):
    def __init__(
        self,
        profiles: ConnectionProfileRepository,
        endpoints: EndpointProvider,
        propagator: RecordPropagator,
    ) -> None:
        super().__init__(profiles, endpoints)
        self._propagator = propagator

    async def execute(
        self, profile_id: int, resource: str, record_id: str, fields: dict[str, Any]
    ) -> RecordWrite:
        """Edit ONE record, then write the change through to its counterparts. Only fields of the
        resource schema that are not read-only are accepted. Raises ``RecordRejected`` (field
        errors per name) and ``ResourceNotFound``."""
        endpoint = await self._endpoint(profile_id)
        schema = await endpoint.describe(resource)
        _check_editable(schema, fields)
        updated = await endpoint.update(resource, record_id, fields)
        outcomes = await self._propagator.propagate_update(profile_id, resource, record_id, updated)
        return RecordWrite(updated, tuple(outcomes))


def _check_editable(schema: ResourceSchema, fields: dict[str, Any]) -> None:
    if not fields:
        raise RecordRejected("no fields to change")
    errors: dict[str, str] = {}
    for name in fields:
        spec = schema.field(name)
        if spec is None or name == schema.id_field:
            errors[name] = "unknown field" if spec is None else "the id cannot be changed"
        elif spec.readonly:
            errors[name] = "read-only field"
    if errors:
        detail = "; ".join(f"{name}: {why}" for name, why in sorted(errors.items()))
        raise RecordRejected(f"cannot edit {schema.name}: {detail}", errors)


class DeleteRecord(_Base):
    def __init__(
        self,
        profiles: ConnectionProfileRepository,
        endpoints: EndpointProvider,
        xrefs: XRefRepository,
        propagator: RecordPropagator,
    ) -> None:
        super().__init__(profiles, endpoints)
        self._xrefs = xrefs
        self._propagator = propagator

    async def execute(self, profile_id: int, resource: str, record_id: str) -> RecordDelete:
        """Delete ONE record, delete its counterparts, then forget the remaining xrefs.

        Idempotent: a record that no longer exists is a success (the goal is met), the stale xrefs
        are forgotten and nothing is propagated. Raises ``ResourceNotFound`` only for an unknown
        resource and ``RecordRejected`` when the remote refuses (xrefs untouched, the record
        still exists).
        A counterpart that refuses keeps its pair linked, so the other xrefs are left alone too:
        the next job run reconciles them.
        """
        endpoint = await self._endpoint(profile_id)
        try:
            await endpoint.delete(resource, record_id)
        except ResourceNotFound:
            await endpoint.describe(resource)  # an unknown resource is still an error
            await self._forget(profile_id, resource, record_id)
            return RecordDelete(already_deleted=True)
        outcomes = await self._propagator.propagate_delete(profile_id, resource, record_id)
        if not any(o.action == "failed" for o in outcomes):
            await self._forget(profile_id, resource, record_id)
        return RecordDelete(tuple(outcomes))

    async def _forget(self, profile_id: int, resource: str, record_id: str) -> None:
        try:
            await self._xrefs.forget_target(profile_id, resource, record_id)
            await self._xrefs.forget_source(profile_id, resource, record_id)
        except Exception:  # the record is already deleted: report that, never fail the request
            logger.exception("could not forget the sync cross-references of a deleted record")
