"""Shared pagination and batching limits for the use cases, adapters and the API layer."""

MAX_PAGE_SIZE = 1000
# Odoo batches (keyset iteration, chunked read/create/write) and streamed exports.
DEFAULT_BATCH_SIZE = 500
MAX_BATCH_SIZE = 5000
# Upper bound for concurrent in-flight Odoo calls.
DEFAULT_MAX_CONCURRENCY = 8
MAX_CONCURRENCY = 64
