"""Customer use cases."""

import asyncio
from collections.abc import AsyncIterator, Sequence
from dataclasses import replace

from conector_odoo.application.pagination import MAX_PAGE_SIZE, validate_batch_size
from conector_odoo.domain.entities import (
    BulkItemResult,
    BulkUpsertResult,
    Customer,
    CustomerData,
    CustomerFilter,
    CustomerQuery,
    CustomerUpdate,
    CustomerUpsert,
    RejectedItem,
)
from conector_odoo.domain.errors import (
    BatchPartiallyApplied,
    ConnectorError,
    OdooNotFound,
    OdooValidationError,
)
from conector_odoo.domain.ports import CustomerRepository


class CreateCustomer:
    def __init__(self, customers: CustomerRepository) -> None:
        self._customers = customers

    async def execute(self, data: CustomerData) -> Customer:
        if not data.name.strip():
            raise OdooValidationError("customer name must not be blank")
        return await self._customers.create(data)


class UpdateCustomer:
    def __init__(self, customers: CustomerRepository) -> None:
        self._customers = customers

    async def execute(self, customer_id: int, update: CustomerUpdate) -> Customer:
        if update.is_empty():
            raise OdooValidationError("update must change at least one field")
        if update.name is not None and not update.name.strip():
            raise OdooValidationError("customer name must not be blank")
        return await self._customers.update(customer_id, update)


class GetCustomer:
    def __init__(self, customers: CustomerRepository) -> None:
        self._customers = customers

    async def execute(self, customer_id: int) -> Customer:
        customer = await self._customers.get(customer_id)
        if customer is None:
            raise OdooNotFound(f"customer {customer_id} not found")
        return customer


class SearchCustomers:
    def __init__(self, customers: CustomerRepository) -> None:
        self._customers = customers

    async def execute(self, query: CustomerQuery) -> list[Customer]:
        if not 1 <= query.limit <= MAX_PAGE_SIZE:
            raise OdooValidationError(f"limit must be between 1 and {MAX_PAGE_SIZE}")
        if query.offset < 0:
            raise OdooValidationError("offset must not be negative")
        return await self._customers.search(query)


class ExportCustomers:
    """Stream all matching customers as batches (bounded memory, for exports)."""

    def __init__(self, customers: CustomerRepository) -> None:
        self._customers = customers

    def execute(
        self, filters: CustomerFilter, batch_size: int | None = None
    ) -> AsyncIterator[list[Customer]]:
        validate_batch_size(batch_size)  # eager: fails before any streaming starts
        return self._customers.iter_batches(filters, batch_size)


UPDATE_CONCURRENCY = 8


def _normalize_email(email: str | None) -> str | None:
    cleaned = (email or "").strip().lower()
    return cleaned or None


class BulkUpsertCustomers:
    """Create or update many customers matched by email, with per-item results.

    * Emails are normalized (stripped, lowercased) and matched case-insensitively against
      existing customers with ONE batched lookup (``find_by_emails``), never one per item.
    * Items without an email are always created. A repeated email inside the payload fails
      every occurrence after the first (the first one is processed).
    * Per-item problems (rejected input, blank name, unknown country, duplicate email, a failed
      update) become ``failed`` results and never abort the batch.
    * New customers are created with ``create_many`` (chunked). If it raises
      ``BatchPartiallyApplied`` the ids already created are kept as ``created`` and the remaining
      new items are ``failed`` (not applied, or applied with an unknown outcome in the failed
      chunk: verify in Odoo before retrying). Any other create error fails every new item.
    * Existing customers are updated with only the provided fields that actually differ; an
      unchanged record is reported ``updated`` without a write.
    """

    def __init__(self, customers: CustomerRepository, update_concurrency: int = UPDATE_CONCURRENCY):
        self._customers = customers
        self._update_concurrency = update_concurrency

    async def execute(
        self, items: Sequence[CustomerUpsert | RejectedItem], match_by: str = "email"
    ) -> BulkUpsertResult:
        if match_by != "email":
            raise OdooValidationError("match_by only supports 'email'")
        results: dict[int, BulkItemResult] = {}

        def fail(index: int, error: str) -> None:
            results[index] = BulkItemResult(index, "failed", None, error)

        codes = {
            item.country_code.upper()
            for item in items
            if isinstance(item, CustomerUpsert) and item.country_code
        }
        known = await self._customers.known_country_codes(codes) if codes else set()

        valid: list[tuple[int, CustomerUpsert, str | None]] = []
        seen: dict[str, int] = {}
        for index, item in enumerate(items):
            if isinstance(item, RejectedItem):
                fail(index, item.reason)
                continue
            if not item.name.strip():
                fail(index, "customer name must not be blank")
                continue
            code = item.country_code.upper() if item.country_code else None
            if code is not None and code not in known:
                fail(index, f"unknown country code {code!r}")
                continue
            email = _normalize_email(item.email)
            if email is not None:
                if email in seen:
                    fail(index, f"duplicate email in payload (first seen at index {seen[email]})")
                    continue
                seen[email] = index
            valid.append((index, item, email))

        emails = sorted(seen)
        existing = await self._customers.find_by_emails(emails) if emails else {}

        to_create: list[tuple[int, CustomerData]] = []
        to_update: list[tuple[int, Customer, dict[str, object]]] = []
        for index, item, email in valid:
            match = existing.get(email) if email is not None else None
            if match is None:
                data = item.to_data()
                to_create.append((index, _with_email(data, email)))
            else:
                to_update.append((index, match, _changes(item.to_update(), match)))

        await self._create(to_create, results)
        await self._update(to_update, results)
        return BulkUpsertResult([results[i] for i in sorted(results)])

    async def _create(
        self, to_create: list[tuple[int, CustomerData]], results: dict[int, BulkItemResult]
    ) -> None:
        if not to_create:
            return
        created: list[int]
        error: str | None = None
        try:
            created = await self._customers.create_many([data for _, data in to_create])
        except BatchPartiallyApplied as exc:
            created = exc.created_ids
            error = (
                f"not applied: batch partially applied ({exc}); "
                "verify in Odoo before retrying this item"
            )
        except ConnectorError as exc:
            created = []
            error = str(exc)
        for position, (index, _) in enumerate(to_create):
            if position < len(created):
                results[index] = BulkItemResult(index, "created", created[position])
            else:
                results[index] = BulkItemResult(index, "failed", None, error or "not created")

    async def _update(
        self,
        to_update: list[tuple[int, Customer, dict[str, object]]],
        results: dict[int, BulkItemResult],
    ) -> None:
        gate = asyncio.Semaphore(self._update_concurrency)

        async def one(index: int, existing: Customer, changes: dict[str, object]) -> None:
            customer_id = existing.id
            assert customer_id is not None  # persisted customers always have an id
            async with gate:
                try:
                    if changes:
                        await self._customers.apply_update(customer_id, CustomerUpdate(**changes))  # type: ignore[arg-type]
                except ConnectorError as exc:
                    results[index] = BulkItemResult(index, "failed", None, str(exc))
                else:
                    results[index] = BulkItemResult(index, "updated", customer_id)

        await asyncio.gather(*(one(i, c, ch) for i, c, ch in to_update))


def _with_email(data: CustomerData, email: str | None) -> CustomerData:
    return replace(data, email=email)


def _changes(update: CustomerUpdate, existing: Customer) -> dict[str, object]:
    """Provided fields that differ from the stored record (country codes compare uppercased)."""
    changes: dict[str, object] = {}
    for key, value in update.changes().items():
        current = getattr(existing, key)
        if key == "country_code":
            if str(value).upper() != (current or "").upper():
                changes[key] = value
        elif value != current:
            changes[key] = value
    return changes
