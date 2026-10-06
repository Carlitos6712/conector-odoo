"""Shared pagination and batching limits for the use cases, adapters and the API layer."""

from conector_odoo.domain.errors import OdooValidationError

MAX_PAGE_SIZE = 1000
# Odoo batches (keyset iteration, chunked read/create/write) and streamed exports.
DEFAULT_BATCH_SIZE = 500
MAX_BATCH_SIZE = 5000
# Upper bound for concurrent in-flight Odoo calls.
DEFAULT_MAX_CONCURRENCY = 8
MAX_CONCURRENCY = 64
# Max items accepted by one bulk upsert request (POST /customers/bulk).
DEFAULT_BULK_MAX_ITEMS = 1000
MAX_BULK_MAX_ITEMS = 10000


def validate_batch_size(batch_size: int | None) -> None:
    """Raise ``OdooValidationError`` unless ``batch_size`` is ``None`` or within bounds."""
    if batch_size is not None and not 1 <= batch_size <= MAX_BATCH_SIZE:
        raise OdooValidationError(f"batch_size must be between 1 and {MAX_BATCH_SIZE}")
