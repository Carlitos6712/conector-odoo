"""Sync runner: executes a sync job between two ``RecordEndpoint`` systems.

Algorithm (one *pass* moves records from a source endpoint to a destination endpoint; an
``A_TO_B`` job runs the forward pass only):

1. Stream the source in batches (``batch_size``, job filter). Per record, apply the pass mapping.
   A mapping error fails that record only; the run never aborts because of data.
2. ``content hash`` = SHA-256 of the canonical JSON of the mapped fields.
3. Resolve the destination record: a cross-reference (xref) hit means update; otherwise, with a
   ``field:<name>`` upsert key, ``find_by`` on the destination adopts a matching record (update,
   xref written); otherwise create with the idempotency key
   ``sync:{job_id}:{source_id}:{content_hash}`` and write the xref.
4. A record whose hash equals the hash stored in its xref is *skipped*, so re-running an
   unchanged job writes nothing.
5. Per-record failures (``RecordRejected``, ``RemoteUnavailable`` for one record, ...) are stored
   in ``run_errors`` (redacted payload, retryable flag) and processing continues.
   ``RemoteAuthError`` or a missing resource aborts the run as ``failed``; so does exceeding
   ``RunnerConfig.max_errors``.
6. After every batch the counters, the checkpoint and a heartbeat are persisted and errors are
   flushed.

Dry run performs steps 1-4 with reads only: no destination writes, no xref writes; counters
mean would-create / would-update / would-skip and a bounded sample of mapped records is kept.

Time (``clock``) and waiting (``sleep``) are injected so the runner is deterministic in tests.
"""

import hashlib
import json
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

from conector_odoo.domain.errors import (
    ConnectorError,
    MappingNotFound,
    RecordRejected,
    RemoteAuthError,
    RemoteUnavailable,
    ResourceNotFound,
    SyncJobNotFound,
)
from conector_odoo.domain.mapping import MappingDefinition
from conector_odoo.domain.mapping_engine import apply_mapping
from conector_odoo.domain.ports import (
    MappingRepository,
    RecordEndpoint,
    SyncJobRepository,
    SyncRunRepository,
    XRefRepository,
)
from conector_odoo.domain.records import Record
from conector_odoo.domain.sync import MappingRef, SyncJob, TriggerKind
from conector_odoo.domain.sync_runs import (
    ErrorKind,
    RunCounters,
    RunErrorData,
    RunStatus,
    Side,
    SyncRun,
    XRef,
    redact_payload,
)

EndpointFactory = Callable[[int], Awaitable[RecordEndpoint]]
Clock = Callable[[], datetime]
Sleep = Callable[[float], Awaitable[None]]


@dataclass(frozen=True, slots=True)
class RunnerConfig:
    max_errors: int = 1000  # abort the run as failed past this many failed records
    stale_after: timedelta = timedelta(minutes=15)  # a silent 'running' run counts as crashed
    batch_pause: float = 0.0  # seconds to wait between batches (throttling); 0 = none
    sample_limit: int = 20  # dry-run: mapped records kept as a sample


class _Abort(Exception):
    """Stops the run with status ``failed``; the message is stored in ``run.error``."""


@dataclass(frozen=True, slots=True)
class _Pass:
    name: str
    src: RecordEndpoint
    dst: RecordEndpoint
    src_resource: str
    dst_resource: str
    mapping: MappingDefinition
    src_side: Side

    @property
    def forward(self) -> bool:
        return self.name == "forward"


@dataclass(slots=True)
class _State:
    counters: RunCounters
    checkpoint: dict[str, Any]
    errors: list[RunErrorData] = field(default_factory=list)
    error_total: int = 0
    sample: list[dict[str, Any]] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class _Ctx:
    job: SyncJob
    run: SyncRun
    passes: tuple[_Pass, ...]
    state: _State


def content_hash(fields: dict[str, Any]) -> str:
    canonical = json.dumps(fields, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode()).hexdigest()


class SyncRunner:
    def __init__(
        self,
        jobs: SyncJobRepository,
        runs: SyncRunRepository,
        xrefs: XRefRepository,
        mappings: MappingRepository,
        endpoints: EndpointFactory,
        *,
        clock: Clock = lambda: datetime.now(UTC),
        sleep: Sleep,
        config: RunnerConfig = RunnerConfig(),  # noqa: B008 - frozen value object
    ) -> None:
        self._jobs = jobs
        self._runs = runs
        self._xrefs = xrefs
        self._mappings = mappings
        self._endpoints = endpoints
        self._clock = clock
        self._sleep = sleep
        self._config = config

    async def run(
        self,
        job_id: int,
        *,
        trigger: TriggerKind = TriggerKind.MANUAL,
        dry_run: bool = False,
    ) -> SyncRun:
        """Run the job once. Raises ``SyncJobNotFound`` or ``JobAlreadyRunning``; every other
        failure ends the run with status ``failed`` instead of raising."""
        job = await self._jobs.get(job_id)
        if job is None:
            raise SyncJobNotFound(f"sync job {job_id} not found")
        now = self._clock()
        run = await self._runs.create(
            job_id,
            trigger.value,
            dry_run=dry_run,
            started_at=now,
            stale_before=now - self._config.stale_after,
        )
        return await self._drive(job, run)

    # -- orchestration ---------------------------------------------------------------------

    async def _drive(self, job: SyncJob, run: SyncRun) -> SyncRun:
        state = _State(counters=run.counters, checkpoint=dict(run.checkpoint))
        status, error = RunStatus.SUCCEEDED, None
        try:
            ctx = _Ctx(job, run, await self._build_passes(job), state)
            for pass_ in ctx.passes:
                await self._run_pass(ctx, pass_)
            status = self._final_status(state)
        except _Abort as abort:
            status, error = RunStatus.FAILED, str(abort)
        except RemoteAuthError:
            status, error = RunStatus.FAILED, "authentication failed on a remote system"
        except RemoteUnavailable as exc:
            status, error = RunStatus.FAILED, f"remote system unavailable: {exc}"
        except (ResourceNotFound, MappingNotFound) as exc:
            status, error = RunStatus.FAILED, f"configuration error: {exc}"
        await self._finalize(run, state, status, error)
        finished = await self._runs.get(run.id)
        assert finished is not None
        return finished

    async def _build_passes(self, job: SyncJob) -> tuple[_Pass, ...]:
        source = await self._endpoints(job.source.profile_id)
        target = await self._endpoints(job.target.profile_id)
        forward = await self._load_mapping(job.mapping)
        return (
            _Pass(
                "forward",
                source,
                target,
                job.source.resource,
                job.target.resource,
                forward,
                Side.SOURCE,
            ),
        )

    async def _load_mapping(self, ref: MappingRef) -> MappingDefinition:
        stored = await self._mappings.get(ref.name, ref.version)
        if stored is None:
            raise MappingNotFound(f"mapping {ref.name!r} (version {ref.version}) not found")
        return stored.definition

    @staticmethod
    def _final_status(state: _State) -> RunStatus:
        counters = state.counters
        if counters.failed == 0:
            return RunStatus.SUCCEEDED
        if counters.created + counters.updated + counters.skipped == 0:
            return RunStatus.FAILED
        return RunStatus.PARTIAL

    async def _finalize(
        self, run: SyncRun, state: _State, status: RunStatus, error: str | None
    ) -> None:
        await self._flush_errors(run, state)
        await self._runs.finish(
            run.id,
            status,
            self._clock(),
            state.counters,
            error=error,
            sample=state.sample,
        )

    async def _flush_errors(self, run: SyncRun, state: _State) -> None:
        if state.errors:
            await self._runs.add_errors(run.id, state.errors)
            state.errors.clear()

    # -- one pass --------------------------------------------------------------------------

    async def _run_pass(self, ctx: _Ctx, pass_: _Pass) -> None:
        state = ctx.state
        stream = pass_.src.iter_batches(
            pass_.src_resource, ctx.job.record_filter, ctx.job.batch_size
        )
        async for batch in stream:
            for record in batch:
                await self._process(ctx, pass_, record)
            state.checkpoint = {"pass": pass_.name, "last_id": batch[-1].id}
            await self._flush_errors(ctx.run, state)
            await self._runs.save_progress(
                ctx.run.id, state.counters, state.checkpoint, self._clock()
            )
            if self._config.batch_pause > 0:
                await self._sleep(self._config.batch_pause)

    async def _process(self, ctx: _Ctx, pass_: _Pass, record: Record) -> None:
        ref = record.id or ""
        mapped = apply_mapping(pass_.mapping, record)
        if mapped.errors:
            detail = "; ".join(f"{e.rule_target}: {e.message}" for e in mapped.errors)
            self._fail(
                ctx,
                pass_,
                ref,
                f"mapping failed: {detail}",
                ErrorKind.MAPPING,
                retryable=False,
                payload={"source": dict(record.fields)},
            )
            return
        try:
            await self._sync_record(ctx, pass_, record, mapped.fields)
        except RecordRejected as exc:
            self._fail(
                ctx,
                pass_,
                ref,
                f"rejected by the remote system: {exc}",
                ErrorKind.REJECTED,
                retryable=False,
                payload={"fields": mapped.fields, "field_errors": exc.field_errors},
            )
        except RemoteUnavailable as exc:
            self._fail(
                ctx,
                pass_,
                ref,
                f"remote system unavailable: {exc}",
                ErrorKind.REMOTE,
                retryable=True,
                payload={"fields": mapped.fields},
            )
        except (RemoteAuthError, ResourceNotFound):
            raise
        except ConnectorError as exc:
            self._fail(
                ctx,
                pass_,
                ref,
                str(exc),
                ErrorKind.OTHER,
                retryable=True,
                payload={"fields": mapped.fields},
            )

    def _fail(
        self,
        ctx: _Ctx,
        pass_: _Pass,
        ref: str,
        message: str,
        kind: ErrorKind,
        *,
        retryable: bool,
        payload: dict[str, Any],
    ) -> None:
        state = ctx.state
        state.counters.failed += 1
        state.error_total += 1
        state.errors.append(
            RunErrorData(
                record_ref=ref,
                message=message,
                side=pass_.src_side,
                kind=kind,
                retryable=retryable,
                payload=redact_payload(payload),
            )
        )
        if state.error_total > self._config.max_errors:
            raise _Abort(f"aborted: more than {self._config.max_errors} errors")

    async def _sync_record(
        self, ctx: _Ctx, pass_: _Pass, record: Record, fields: dict[str, Any]
    ) -> None:
        job, state = ctx.job, ctx.state
        source_id = record.id or ""
        digest = content_hash(fields)
        xref = await self._xrefs.get_target(job.id or 0, job.source.resource, source_id)
        if xref is not None and xref.content_hash == digest:
            state.counters.skipped += 1
            self._sample(ctx, "skip", source_id, xref.target_id, fields)
            return
        target_id = xref.target_id if xref is not None else await self._adopt(ctx, pass_, fields)
        dry = ctx.run.dry_run
        if target_id is not None:
            action = "update"
            if not dry:
                written = await pass_.dst.update(pass_.dst_resource, target_id, fields)
                target_id = written.id or target_id
            state.counters.updated += 1
        else:
            action = "create"
            if not dry:
                key = f"sync:{job.id}:{source_id}:{digest}"
                written = await pass_.dst.create(pass_.dst_resource, fields, key)
                target_id = written.id or ""
            state.counters.created += 1
        self._sample(ctx, action, source_id, target_id, fields)
        if not dry and target_id is not None:
            await self._xrefs.upsert(
                XRef(
                    job.id or 0,
                    job.source.resource,
                    source_id,
                    target_id,
                    digest,
                    None,
                    self._clock(),
                )
            )

    async def _adopt(self, ctx: _Ctx, pass_: _Pass, fields: dict[str, Any]) -> str | None:
        """Id of an existing destination record matching the job's ``field:<name>`` key."""
        key_field = ctx.job.key_field
        if key_field is None:
            return None
        value = Record(None, fields).get(key_field)
        if value is None:
            return None
        found = await pass_.dst.find_by(pass_.dst_resource, key_field, value)
        return None if found is None else found.id

    def _sample(
        self, ctx: _Ctx, action: str, source_id: str, target_id: str | None, fields: dict[str, Any]
    ) -> None:
        if ctx.run.dry_run and len(ctx.state.sample) < self._config.sample_limit:
            ctx.state.sample.append(
                {
                    "action": action,
                    "source_id": source_id,
                    "target_id": target_id,
                    "fields": redact_payload(fields),
                }
            )
