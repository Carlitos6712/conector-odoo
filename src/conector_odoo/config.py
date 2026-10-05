"""Application settings loaded from environment variables and an optional ``.env`` file."""

from functools import lru_cache
from typing import Literal

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from conector_odoo.application.pagination import (
    DEFAULT_BATCH_SIZE,
    DEFAULT_BULK_MAX_ITEMS,
    DEFAULT_MAX_CONCURRENCY,
    MAX_BATCH_SIZE,
    MAX_BULK_MAX_ITEMS,
    MAX_CONCURRENCY,
)
from conector_odoo.infrastructure.idempotency.store import DEFAULT_IN_PROGRESS_TIMEOUT_SECONDS

OdooProtocol = Literal["jsonrpc", "xmlrpc", "json2"]
MIN_SECRET_LENGTH = 16


class Settings(BaseSettings):
    """Connector configuration. Secrets are ``SecretStr`` so they never leak via repr/logs."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        env_ignore_empty=True,
        hide_input_in_errors=True,  # validation errors must not echo (short) secrets
    )

    odoo_url: str
    odoo_db: str
    odoo_user: str
    odoo_api_key: SecretStr
    odoo_protocol: OdooProtocol = "jsonrpc"
    odoo_timeout_seconds: float = 10.0
    odoo_max_retries: int = 2
    odoo_company_id: int | None = None
    # Max Odoo calls in flight at once (also the HTTP connection pool size).
    odoo_max_concurrency: int = Field(default=DEFAULT_MAX_CONCURRENCY, ge=1, le=MAX_CONCURRENCY)
    # Default page size of keyset iteration and chunked Odoo operations.
    odoo_batch_size: int = Field(default=DEFAULT_BATCH_SIZE, ge=1, le=MAX_BATCH_SIZE)
    # Max items accepted by a single bulk upsert payload.
    bulk_max_items: int = Field(default=DEFAULT_BULK_MAX_ITEMS, ge=1, le=MAX_BULK_MAX_ITEMS)

    connector_api_key: SecretStr | None = None
    webhook_secret: SecretStr

    idempotency_db_path: str = "./data/idempotency.sqlite3"
    # Admin database (profiles, mappings, jobs, runs, users); migrated at startup.
    admin_db_path: str = "./data/admin.db"
    # An ``in_progress`` key older than this is treated as abandoned (outcome unknown).
    idempotency_in_progress_timeout_seconds: float = DEFAULT_IN_PROGRESS_TIMEOUT_SECONDS
    # Records older than this are purged (at startup and every purge interval).
    idempotency_ttl_hours: float = 24.0
    idempotency_purge_interval_seconds: float = 3600.0
    # Max clock skew (seconds) between Odoo's signed timestamp and ours; bounds replay windows.
    webhook_tolerance_seconds: int = 300
    # A ``received`` webhook event older than this is re-dispatched when Odoo redelivers it
    # (at-least-once); a newer one is treated as still in flight.
    webhook_redelivery_after_seconds: float = 60.0
    log_level: str = "INFO"

    @field_validator("odoo_api_key", "connector_api_key", "webhook_secret")
    @classmethod
    def _secret_is_long_enough(cls, value: SecretStr | None) -> SecretStr | None:
        # Odoo API keys are 40 hex characters; every secret here is also scrubbed from messages.
        if value is not None and len(value.get_secret_value()) < MIN_SECRET_LENGTH:
            raise ValueError(f"must be at least {MIN_SECRET_LENGTH} characters long")
        return value


@lru_cache
def get_settings() -> Settings:
    """Return the process-wide settings instance (cached)."""
    return Settings()
