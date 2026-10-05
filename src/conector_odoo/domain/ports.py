"""Ports (async Protocols) implemented by infrastructure adapters."""

from collections.abc import AsyncIterator, Awaitable, Callable
from typing import Any, Protocol, runtime_checkable

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
from conector_odoo.domain.profiles import (
    ConnectionProfile,
    ProbeStep,
    Secrets,
    StoredProfile,
)
from conector_odoo.domain.records import Record, RecordFilter, ResourceSchema
from conector_odoo.domain.resources import ResourceConfig, ResourceSource, StoredResource

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

    ``create`` and ``update`` raise ``RecordRejected`` when the remote refuses the data.
    """

    async def describe(self, resource: str) -> ResourceSchema: ...

    async def find_by(self, resource: str, field: str, value: Any) -> Record | None: ...

    async def create(self, resource: str, fields: dict[str, Any], idempotency_key: str) -> Record:
        """Create a record; replaying the same ``idempotency_key`` returns the same record."""
        ...

    async def update(self, resource: str, id: str, fields: dict[str, Any]) -> Record: ...


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

    async def list(self, profile_id: int) -> list[StoredResource]: ...

    async def delete(self, profile_id: int, name: str) -> None:
        """Raises ``CatalogResourceNotFound``."""
        ...
