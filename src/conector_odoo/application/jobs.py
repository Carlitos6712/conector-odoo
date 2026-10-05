"""Use cases for sync jobs and for reading runs.

Creating or editing a job checks that its mappings exist and really map the job's resources
(forward: source resource to target resource; reverse: the other way round), because a mismatched
mapping would only surface as a stream of per-record errors in the first run.
"""

from dataclasses import replace

from conector_odoo.domain.errors import (
    MappingNotFound,
    SyncJobInvalid,
    SyncJobNotFound,
    SyncRunNotFound,
)
from conector_odoo.domain.mapping import MappingDefinition
from conector_odoo.domain.ports import MappingRepository, SyncJobRepository, SyncRunRepository
from conector_odoo.domain.sync import MappingRef, SyncJob
from conector_odoo.domain.sync_runs import RunError, RunFilter, SyncRun


async def _definition(mappings: MappingRepository, ref: MappingRef) -> MappingDefinition:
    stored = await mappings.get(ref.name, ref.version)
    if stored is None:
        suffix = "" if ref.version is None else f" version {ref.version}"
        raise MappingNotFound(f"mapping {ref.name!r}{suffix} not found")
    return stored.definition


async def check_job_mappings(job: SyncJob, mappings: MappingRepository) -> None:
    """Raises ``MappingNotFound`` or ``SyncJobInvalid``."""
    forward = await _definition(mappings, job.mapping)
    if (forward.source_resource, forward.target_resource) != (
        job.source.resource,
        job.target.resource,
    ):
        raise SyncJobInvalid(
            f"mapping {job.mapping.name!r} maps {forward.source_resource!r} to "
            f"{forward.target_resource!r}, but the job syncs {job.source.resource!r} to "
            f"{job.target.resource!r}"
        )
    if job.reverse_mapping is not None:
        reverse = await _definition(mappings, job.reverse_mapping)
        if (reverse.source_resource, reverse.target_resource) != (
            job.target.resource,
            job.source.resource,
        ):
            raise SyncJobInvalid(
                f"reverse mapping {job.reverse_mapping.name!r} maps {reverse.source_resource!r} "
                f"to {reverse.target_resource!r}, but it must map {job.target.resource!r} to "
                f"{job.source.resource!r}"
            )


class CreateJob:
    def __init__(self, jobs: SyncJobRepository, mappings: MappingRepository) -> None:
        self._jobs = jobs
        self._mappings = mappings

    async def execute(self, job: SyncJob) -> SyncJob:
        """Raises ``SyncJobNameTaken``, ``ProfileNotFound``, ``MappingNotFound``,
        ``SyncJobInvalid``."""
        await check_job_mappings(job, self._mappings)
        return await self._jobs.add(job)


class UpdateJob:
    def __init__(self, jobs: SyncJobRepository, mappings: MappingRepository) -> None:
        self._jobs = jobs
        self._mappings = mappings

    async def execute(self, job_id: int, job: SyncJob) -> SyncJob:
        """Raises ``SyncJobNotFound`` plus the ``CreateJob`` errors."""
        await check_job_mappings(job, self._mappings)
        return await self._jobs.update(replace(job, id=job_id))


class GetJob:
    def __init__(self, jobs: SyncJobRepository) -> None:
        self._jobs = jobs

    async def execute(self, job_id: int) -> SyncJob:
        job = await self._jobs.get(job_id)
        if job is None:
            raise SyncJobNotFound(f"sync job {job_id} not found")
        return job


class ListJobs:
    def __init__(self, jobs: SyncJobRepository) -> None:
        self._jobs = jobs

    async def execute(self) -> list[SyncJob]:
        return await self._jobs.list()


class DeleteJob:
    def __init__(self, jobs: SyncJobRepository) -> None:
        self._jobs = jobs

    async def execute(self, job_id: int) -> None:
        """Raises ``SyncJobNotFound`` or ``SyncJobInUse`` (the run history is kept)."""
        await self._jobs.delete(job_id)


class ListRuns:
    def __init__(self, runs: SyncRunRepository) -> None:
        self._runs = runs

    async def execute(
        self, run_filter: RunFilter, limit: int = 50, offset: int = 0
    ) -> list[SyncRun]:
        return await self._runs.list_runs(run_filter, limit, offset)


class GetRun:
    def __init__(self, runs: SyncRunRepository) -> None:
        self._runs = runs

    async def execute(self, run_id: int) -> tuple[SyncRun, int]:
        """The run and its error count. Raises ``SyncRunNotFound``."""
        run = await self._runs.get(run_id)
        if run is None:
            raise SyncRunNotFound(f"sync run {run_id} not found")
        return run, await self._runs.count_errors(run_id)


class ListRunErrors:
    def __init__(self, runs: SyncRunRepository) -> None:
        self._runs = runs

    async def execute(
        self, run_id: int, limit: int = 100, offset: int = 0, *, only_unretried: bool = False
    ) -> tuple[list[RunError], int]:
        """A page of errors and the run's total. Raises ``SyncRunNotFound``."""
        await GetRun(self._runs).execute(run_id)
        errors = await self._runs.list_errors(run_id, limit, offset, only_unretried=only_unretried)
        return errors, await self._runs.count_errors(run_id)
