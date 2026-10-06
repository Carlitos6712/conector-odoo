"""Ports (async Protocols) implemented by infrastructure adapters."""

from collections.abc import AsyncIterator, Awaitable, Callable, Sequence
from datetime import datetime
from typing import Any, Protocol, runtime_checkable

from conector_odoo.domain.active_odoo import OdooSource
from conector_odoo.domain.auth import AdminSession, AdminUser, Role
from conector_odoo.domain.entities import (
    Customer,
    CustomerData,
    CustomerFilter,
    CustomerQuery,
    CustomerUpdate,
    Product,
    SaleOrder,
    SaleOrderData,
)
from conector_odoo.domain.events import OdooEvent
from conector_odoo.domain.mapping import MappingDefinition, StoredMapping
from conector_odoo.domain.profiles import (
    ConnectionProfile,
    ProbeStep,
    Secrets,
    StoredProfile,
)
from conector_odoo.domain.records import Record, RecordFilter, ResourceSchema
from conector_odoo.domain.resources import (
    CatalogListing,
    ResourceConfig,
    ResourceSource,
    StoredResource,
)
from conector_odoo.domain.sync import SyncJob
from conector_odoo.domain.sync_runs import (
    RunCounters,
    RunError,
    RunErrorData,
    RunFilter,
    RunStatus,
    SyncRun,
    XRef,
)

EventHandler = Callable[[OdooEvent], Awaitable[None]]


class CustomerRepository(Protocol):
    async def create(self, data: CustomerData) -> Customer: ...

    async def update(self, customer_id: int, update: CustomerUpdate) -> Customer: ...

    async def get(self, customer_id: int) -> Customer | None: ...

    async def search(self, query: CustomerQuery) -> list[Customer]: ...

    async def archive(self, customer_id: int) -> None: ...

    async def find_by_emails(self, emails: list[str]) -> dict[str, Customer]:
        """Find existing customers by email in a few batched lookups (never one per email).

        Matching is case-insensitive and exact. Keys of the result are the lowercased emails;
        when several customers share an email the first one (lowest id) wins.
        """
        ...

    async def create_many(self, data: list[CustomerData]) -> list[int]:
        """Create customers in chunks; returns the new ids in input order.

        Raises ``BatchPartiallyApplied`` (carrying the ids created so far) when a later chunk
        fails.
        """
        ...

    async def apply_update(self, customer_id: int, update: CustomerUpdate) -> None:
        """Write only the provided fields, without reading the record back."""
        ...

    async def known_country_codes(self, codes: set[str]) -> set[str]:
        """Return the subset of ISO country ``codes`` that exist (one batched lookup)."""
        ...

    def iter_batches(
        self, filters: CustomerFilter, batch_size: int | None = None
    ) -> AsyncIterator[list[Customer]]:
        """Stream every matching customer in id order, ``batch_size`` at a time.

        ``batch_size=None`` leaves the choice to the adapter. Only one batch is held in memory.
        """
        ...


class ProductRepository(Protocol):
    async def get(self, product_id: int) -> Product | None: ...

    # Declared before ``list``: inside this class body the name ``list`` would otherwise shadow
    # the builtin in later annotations.
    def iter_batches(self, batch_size: int | None = None) -> AsyncIterator[list[Product]]:
        """Stream every sellable product in id order, ``batch_size`` at a time."""
        ...

    async def list(self, limit: int, offset: int) -> list[Product]: ...


class SaleOrderRepository(Protocol):
    async def create(self, data: SaleOrderData) -> SaleOrder: ...

    async def confirm(self, order_id: int, company_id: int | None = None) -> SaleOrder: ...

    async def get(self, order_id: int, company_id: int | None = None) -> SaleOrder | None: ...


class EventBus(Protocol):
    def subscribe(self, event_type: str, handler: EventHandler) -> None: ...

    async def publish(self, event: OdooEvent) -> bool:
        """Deliver the event to its handlers; ``True`` when every handler succeeded."""
        ...


class ConnectionProfileRepository(Protocol):
    """Persistence of connection profiles; secrets are handled only as an opaque blob."""

    async def add(
        self, profile: ConnectionProfile, secrets_blob: bytes | None
    ) -> ConnectionProfile:
        """Insert; raises ``ProfileNameTaken`` on a duplicate name."""
        ...

    async def update(
        self, profile: ConnectionProfile, secrets_blob: bytes | None
    ) -> ConnectionProfile:
        """Replace every field of ``profile.id`` (``created_at`` is kept).

        Raises ``ProfileNotFound`` / ``ProfileNameTaken``.
        """
        ...

    async def get(self, profile_id: int) -> StoredProfile | None: ...

    async def list(self) -> list[StoredProfile]: ...

    async def delete(self, profile_id: int) -> None:
        """Raises ``ProfileNotFound`` or ``ProfileInUse`` (referenced by resources/jobs)."""
        ...


class AppSettingsRepository(Protocol):
    """Small persistent string key/value store for application state (not user data)."""

    async def get_all(self, prefix: str) -> dict[str, str]:
        """Every entry whose key starts with ``prefix`` (a literal prefix, not a pattern)."""
        ...

    async def set_many(self, values: dict[str, str]) -> None:
        """Upsert all entries in one transaction."""
        ...

    async def delete(self, key: str) -> None: ...


class OdooConnectionInfo(Protocol):
    """Non-secret description of an Odoo connection (live, or built but not installed yet)."""

    @property
    def source(self) -> OdooSource: ...

    @property
    def profile_id(self) -> int | None: ...

    @property
    def profile_name(self) -> str | None: ...

    @property
    def base_url(self) -> str | None: ...

    @property
    def db(self) -> str | None: ...

    @property
    def login(self) -> str | None: ...


PreparedOdooConnection = OdooConnectionInfo  # a prepared connection is discarded via the runtime


class OdooRuntime(Protocol):
    """The live Odoo connection of the process, swappable without a restart.

    Preparing builds a client without any I/O; ``commit`` swaps it in atomically and retires the
    previous one after its in-flight requests finish; ``commit(None)`` disconnects.
    """

    @property
    def current(self) -> OdooConnectionInfo | None: ...

    def prepare_profile(
        self, profile: ConnectionProfile, secrets: Secrets
    ) -> PreparedOdooConnection: ...

    def prepare_env(self) -> PreparedOdooConnection | None:
        """The connection described by the legacy ODOO_* env vars, or ``None`` when incomplete."""
        ...

    async def commit(self, prepared: PreparedOdooConnection | None) -> None: ...

    async def discard(self, prepared: PreparedOdooConnection) -> None: ...


class SecretVault(Protocol):
    """Encrypts/decrypts a profile's ``Secrets``.

    Raises ``VaultNotConfigured`` without a usable key and ``VaultDecryptionError`` when the blob
    cannot be decrypted.
    """

    def encrypt(self, secrets: Secrets) -> bytes: ...

    def decrypt(self, blob: bytes) -> Secrets: ...


class ConnectionProbe(Protocol):
    """Checks a connection of one profile type and returns its ordered steps.

    Steps run in order (``url_valid``, ``reachable``, ``tls``, ``auth``); the first failing step
    is the last one returned.
    """

    async def probe(self, profile: ConnectionProfile, secrets: Secrets) -> list[ProbeStep]: ...


@runtime_checkable
class RecordSource(Protocol):
    """Reads records of any resource from a remote system.

    Raises ``ResourceNotFound``, ``RemoteAuthError`` or ``RemoteUnavailable``.
    """

    async def describe(self, resource: str) -> ResourceSchema: ...

    def iter_batches(
        self, resource: str, record_filter: RecordFilter, batch_size: int
    ) -> AsyncIterator[list[Record]]:
        """Stream matching records, ``batch_size`` at a time; one batch in memory."""
        ...

    async def get(self, resource: str, id: str) -> Record | None: ...

    async def sample(self, resource: str, limit: int) -> list[Record]: ...


@runtime_checkable
class RecordSink(Protocol):
    """Writes records of any resource to a remote system.

    ``create``, ``update`` and ``delete`` raise ``RecordRejected`` when the remote refuses the data.
    """

    async def describe(self, resource: str) -> ResourceSchema: ...

    async def find_by(self, resource: str, field: str, value: Any) -> Record | None: ...

    async def create(self, resource: str, fields: dict[str, Any], idempotency_key: str) -> Record:
        """Create a record; replaying the same ``idempotency_key`` returns the same record."""
        ...

    async def update(self, resource: str, id: str, fields: dict[str, Any]) -> Record: ...

    async def delete(self, resource: str, id: str) -> None:
        """Permanently remove ONE record. Raises ``ResourceNotFound`` when it does not exist and
        ``RecordRejected`` when the remote refuses (still referenced, access rules, unsupported)."""
        ...


@runtime_checkable
class RecordEndpoint(RecordSource, RecordSink, Protocol):
    """A system that can be both read from and written to."""


class ResourceConfigProvider(Protocol):
    """Looks up the ``ResourceConfig`` of a resource name (storage is not the adapter's concern)."""

    async def get(self, resource: str) -> ResourceConfig:
        """Raises ``ResourceNotFound`` when the resource is not configured."""
        ...


class ResourceCatalogRepository(Protocol):
    """Per-profile catalog of REST resource configurations (unique by profile and name)."""

    async def save(
        self, profile_id: int, config: ResourceConfig, source: ResourceSource
    ) -> StoredResource:
        """Insert or replace ``config`` by name. Raises ``ProfileNotFound``."""
        ...

    async def get(self, profile_id: int, name: str) -> StoredResource | None:
        """Raises ``ResourceConfigInvalid`` when the stored JSON is unknown or corrupt."""
        ...

    async def list(self, profile_id: int) -> list[StoredResource]:
        """The readable entries; a corrupt row is skipped (and logged), never fatal."""
        ...

    async def list_with_problems(self, profile_id: int) -> CatalogListing:
        """Like ``list``, and also names every skipped entry with the reason."""
        ...

    async def delete(self, profile_id: int, name: str) -> None:
        """Raises ``CatalogResourceNotFound``."""
        ...


class MappingRepository(Protocol):
    """Versioned storage of mapping definitions (versions are numbered per name from 1)."""

    async def save_new_version(self, definition: MappingDefinition) -> StoredMapping:
        """Store ``definition`` as the next version of its name.

        A definition identical to the latest version returns that version unchanged.
        """
        ...

    async def get(self, name: str, version: int | None = None) -> StoredMapping | None:
        """The given version, or the latest when ``version`` is ``None``.

        Raises ``MappingInvalid`` when the stored JSON is unknown or corrupt.
        """
        ...

    async def list_latest(self) -> list[StoredMapping]:
        """The latest version of every mapping, ordered by name."""
        ...

    async def list_versions(self, name: str) -> list[StoredMapping]:
        """Every version of ``name``, oldest first (empty when the name is unknown)."""
        ...

    async def delete(self, name: str) -> None:
        """Delete every version. Raises ``MappingNotFound`` or ``MappingInUse`` (some version is
        referenced by a sync job)."""
        ...


class SyncJobRepository(Protocol):
    """Persistence of sync jobs (unique by name)."""

    async def add(self, job: SyncJob) -> SyncJob:
        """Insert and return the job with its id. Raises ``SyncJobNameTaken``,
        ``ProfileNotFound`` or ``MappingNotFound`` (a referenced profile/mapping is missing)."""
        ...

    async def update(self, job: SyncJob) -> SyncJob:
        """Replace every field of ``job.id``. Raises ``SyncJobNotFound`` plus the ``add`` errors."""
        ...

    async def get(self, job_id: int) -> SyncJob | None: ...

    async def list(self) -> list[SyncJob]: ...

    async def delete(self, job_id: int) -> None:
        """Also removes the job's xref rows. Raises ``SyncJobNotFound``, or ``SyncJobInUse`` when
        the job has runs (the history is kept)."""
        ...


class SyncRunRepository(Protocol):
    """Runs, their resumable state and their per-record errors."""

    async def create(
        self,
        job_id: int,
        trigger: str,
        *,
        dry_run: bool,
        started_at: datetime,
        stale_before: datetime,
        parent_run_id: int | None = None,
        options: dict[str, Any] | None = None,
    ) -> SyncRun:
        """Insert a ``running`` run unless the job already has an active one.

        An active run whose heartbeat (or start, when it has none) is older than ``stale_before``
        is a crashed run and does not block. Raises ``JobAlreadyRunning`` or ``SyncJobNotFound``.
        """
        ...

    async def get(self, run_id: int) -> SyncRun | None: ...

    async def reopen(
        self, run_id: int, *, heartbeat_at: datetime, stale_before: datetime
    ) -> SyncRun:
        """Set a resumable run back to ``running`` (clearing its finish time and cancel flag).
        Raises ``SyncRunNotFound`` or ``JobAlreadyRunning`` (another run of the job is active)."""
        ...

    async def save_progress(
        self,
        run_id: int,
        counters: RunCounters,
        checkpoint: dict[str, Any],
        heartbeat_at: datetime,
    ) -> None: ...

    async def finish(
        self,
        run_id: int,
        status: RunStatus,
        finished_at: datetime,
        counters: RunCounters,
        *,
        error: str | None = None,
        sample: Sequence[dict[str, Any]] = (),
        warnings: Sequence[str] = (),
    ) -> None:
        """Close the run; non-empty ``warnings`` are kept in its ``options["warnings"]``."""
        ...

    async def request_cancel(self, run_id: int) -> bool:
        """Flag an active run for cancellation; ``False`` when it is not active."""
        ...

    async def is_cancel_requested(self, run_id: int) -> bool: ...

    async def add_errors(self, run_id: int, errors: Sequence[RunErrorData]) -> None:
        """Append errors in one transaction (batched)."""
        ...

    async def list_runs(
        self, run_filter: RunFilter, limit: int = 50, offset: int = 0
    ) -> list[SyncRun]:
        """Newest first."""
        ...

    async def list_errors(
        self, run_id: int, limit: int = 100, offset: int = 0, *, only_unretried: bool = False
    ) -> list[RunError]: ...

    async def count_errors(self, run_id: int) -> int: ...

    async def mark_errors_retried(
        self, run_id: int, side: str, record_refs: Sequence[str]
    ) -> None: ...


class XRefRepository(Protocol):
    """Cross-reference between a source record id (side A) and a target record id (side B)."""

    async def get_target(self, job_id: int, resource: str, source_id: str) -> XRef | None: ...

    async def get_source(self, job_id: int, resource: str, target_id: str) -> XRef | None: ...

    async def upsert(self, xref: XRef) -> None:
        """Insert or replace by (job, resource, source id)."""
        ...

    async def list(
        self, job_id: int, resource: str | None = None, limit: int = 100, offset: int = 0
    ) -> list[XRef]: ...

    async def forget_target(self, profile_id: int, resource: str, target_id: str) -> int:
        """Delete the xref rows of every job whose target is (``profile_id``, ``resource``) and
        that point at ``target_id``; returns how many. Used when that record was deleted outside
        a sync run, so the next run recreates it instead of skipping or updating a missing id."""
        ...

    async def forget_source(self, profile_id: int, resource: str, source_id: str) -> int:
        """Like ``forget_target`` for the source side: every job whose source is
        (``profile_id``, ``resource``) and whose xref points at ``source_id``."""
        ...

    async def forget(self, job_id: int, resource: str, source_id: str) -> int:
        """Delete the xref of one job for the pair whose side-A id is ``source_id``."""
        ...


class PasswordHasher(Protocol):
    """One-way password hashing; ``verify`` never raises for a wrong or malformed hash."""

    def hash(self, password: str) -> str: ...

    def verify(self, password_hash: str, password: str) -> bool: ...


class AdminUserRepository(Protocol):
    """Persistence of local admin users (usernames are unique case-insensitively)."""

    async def add(
        self, username: str, password_hash: str, role: Role, created_at: datetime
    ) -> AdminUser:
        """Raises ``AdminUsernameTaken``."""
        ...

    async def get(self, user_id: int) -> AdminUser | None: ...

    async def get_credentials(self, username: str) -> tuple[AdminUser, str] | None:
        """The user and its password hash, looked up case-insensitively."""
        ...

    async def list(self) -> list[AdminUser]: ...

    async def count(self) -> int: ...

    async def count_admins(self) -> int: ...

    async def update(
        self, user_id: int, *, role: Role | None = None, password_hash: str | None = None
    ) -> AdminUser:
        """Change the given fields. Raises ``AdminUserNotFound``."""
        ...

    async def delete(self, user_id: int) -> None:
        """Also removes the user's sessions. Raises ``AdminUserNotFound``."""
        ...


class SessionStore(Protocol):
    """Server-side admin sessions keyed by the digest of the cookie token."""

    async def create(self, session: AdminSession) -> None: ...

    async def get(self, token_hash: str) -> AdminSession | None: ...

    async def touch(self, token_hash: str, last_seen_at: datetime) -> None: ...

    async def delete(self, token_hash: str) -> None: ...

    async def delete_for_user(self, user_id: int) -> None: ...

    async def purge_expired(self, now: datetime) -> int: ...


class LoginThrottle(Protocol):
    """Failed-login counter with a temporary lockout, per normalised username."""

    async def retry_after(self, key: str, now: datetime) -> int:
        """Seconds until the key may try again; ``0`` when it is not locked."""
        ...

    async def record_failure(
        self, key: str, now: datetime, *, max_failures: int, lock_seconds: int
    ) -> None: ...

    async def reset(self, key: str) -> None: ...


class IpLoginThrottle(Protocol):
    """Sliding-window count of failed logins per client address (normalised key)."""

    async def retry_after(
        self, ip: str, now: datetime, *, max_failures: int, window_seconds: int
    ) -> int:
        """Seconds until ``ip`` may try again; ``0`` when fewer than ``max_failures`` failures
        happened in the last ``window_seconds``."""
        ...

    async def record_failure(self, ip: str, now: datetime, *, window_seconds: int) -> None:
        """Count one failure and forget failures older than the window."""
        ...


class KnownLoginIps(Protocol):
    """Addresses a username signed in from successfully, remembered for a limited time."""

    async def is_known(self, key: str, ip: str, now: datetime, *, max_age_seconds: int) -> bool: ...

    async def remember(self, key: str, ip: str, now: datetime, *, max_age_seconds: int) -> None: ...
