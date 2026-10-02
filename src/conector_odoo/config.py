"""Application settings loaded from environment variables and an optional ``.env`` file."""

from functools import lru_cache
from typing import Literal

from pydantic import SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

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

    connector_api_key: SecretStr | None = None
    webhook_secret: SecretStr

    idempotency_db_path: str = "idempotency.sqlite3"
    log_level: str = "INFO"

    @field_validator("connector_api_key", "webhook_secret")
    @classmethod
    def _secret_is_long_enough(cls, value: SecretStr | None) -> SecretStr | None:
        if value is not None and len(value.get_secret_value()) < MIN_SECRET_LENGTH:
            raise ValueError(f"must be at least {MIN_SECRET_LENGTH} characters long")
        return value


@lru_cache
def get_settings() -> Settings:
    """Return the process-wide settings instance (cached)."""
    return Settings()
