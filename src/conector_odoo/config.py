"""Application settings loaded from environment variables and an optional ``.env`` file."""

from functools import lru_cache
from typing import Literal

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from conector_odoo.application.pagination import (
    DEFAULT_BATCH_SIZE,
    DEFAULT_BULK_MAX_ITEMS,
    DEFAULT_MAX_CONCURRENCY,
    MAX_BATCH_SIZE,
    MAX_BULK_MAX_ITEMS,
    MAX_CONCURRENCY,
)
from conector_odoo.domain.outbound import OutboundPolicy
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
    # Fernet key that encrypts connection-profile secrets at rest. No key is ever generated
    # implicitly: storing or reading a secret without it fails with a clear error.
    encryption_key: SecretStr | None = None
    webhook_secret: SecretStr

    idempotency_db_path: str = "./data/idempotency.sqlite3"
    # Admin database (profiles, mappings, jobs, runs, users); migrated at startup.
    admin_db_path: str = "./data/admin.db"
    # Built admin frontend (``frontend/dist``), relative to the working directory; served at ``/``.
    # A missing directory is harmless: the API keeps working and one warning is logged.
    frontend_dist_dir: str = "./frontend/dist"
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
    # In-process cron scheduler for sync jobs; set SYNC_SCHEDULER_ENABLED=false to turn it off.
    sync_scheduler_enabled: bool = True
    # How often the scheduler reloads the job list (seconds).
    sync_scheduler_refresh_seconds: float = Field(default=60.0, gt=0)
    # -- admin API (/admin/api) ----------------------------------------------------------------
    # First admin, created at startup ONLY when no admin user exists yet. There is no default
    # password: without both values the first admin must be created some other way.
    admin_bootstrap_user: str | None = None
    admin_bootstrap_password: SecretStr | None = None
    admin_cookie_name: str = "admin_session"
    # Secure cookies are only sent over HTTPS (browsers exempt localhost); turn off for plain-HTTP
    # development behind no proxy only.
    admin_cookie_secure: bool = True
    admin_cookie_samesite: Literal["lax", "strict"] = "lax"
    admin_session_ttl_seconds: int = Field(default=12 * 3600, ge=60)
    admin_session_idle_seconds: int = Field(default=2 * 3600, ge=60)
    admin_login_max_failures: int = Field(default=5, ge=1)
    admin_login_lockout_seconds: int = Field(default=900, ge=1)
    # Per client address (sliding window): failed logins / password checks from one address, across
    # all usernames, before that address is blocked with 429.
    admin_login_ip_max_failures: int = Field(default=20, ge=1)
    admin_login_ip_window_seconds: int = Field(default=900, ge=1)
    # How long (days) an address that signed in successfully stays "known" for its username, which
    # lets the owner past a lockout caused by other addresses. 0 disables the bypass.
    admin_login_known_ip_days: int = Field(default=30, ge=0)
    # Number of reverse proxies in front of the app that append to X-Forwarded-For. 0 (default)
    # ignores the header and uses the socket peer; N > 0 takes the N-th entry from the right.
    trusted_proxy_count: int = Field(default=0, ge=0)
    # Argon2id cost; the defaults follow the argon2-cffi/OWASP recommendation. Lower them only on
    # very small hosts or in tests.
    admin_argon2_time_cost: int = Field(default=3, ge=1)
    admin_argon2_memory_kib: int = Field(default=64 * 1024, ge=8)
    admin_argon2_parallelism: int = Field(default=4, ge=1)
    # Outbound URL policy (SSRF): ``default`` always blocks link-local/metadata, unspecified and
    # multicast addresses and non-http(s) schemes; ``strict`` also blocks private and loopback
    # addresses unless the host is in OUTBOUND_ALLOWED_HOSTS (comma-separated names or IPs).
    outbound_url_policy: Literal["default", "strict"] = "default"
    outbound_allowed_hosts: str = ""
    log_level: str = "INFO"

    @model_validator(mode="after")
    def _bootstrap_is_complete(self) -> "Settings":
        if (self.admin_bootstrap_user is None) != (self.admin_bootstrap_password is None):
            raise ValueError(
                "ADMIN_BOOTSTRAP_USER and ADMIN_BOOTSTRAP_PASSWORD must be set together"
            )
        return self

    def outbound_policy(self) -> OutboundPolicy:
        return OutboundPolicy.from_values(self.outbound_url_policy, self.outbound_allowed_hosts)

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
