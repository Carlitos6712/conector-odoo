import pytest
from pydantic import SecretStr, ValidationError

from conector_odoo.config import Settings, get_settings

BASE_ENV = {
    "ODOO_URL": "https://odoo.example.com",
    "ODOO_DB": "prod",
    "ODOO_USER": "bot@example.com",
    "ODOO_API_KEY": "key-1234567890123456",
    "WEBHOOK_SECRET": "hook-secret-0123456",
}


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in (
        "ODOO_PROTOCOL",
        "ODOO_TIMEOUT_SECONDS",
        "ODOO_MAX_RETRIES",
        "ODOO_COMPANY_ID",
        "CONNECTOR_API_KEY",
        "IDEMPOTENCY_DB_PATH",
        "LOG_LEVEL",
    ):
        monkeypatch.delenv(name, raising=False)
    get_settings.cache_clear()


def _set_env(monkeypatch: pytest.MonkeyPatch, **extra: str) -> None:
    for key, value in {**BASE_ENV, **extra}.items():
        monkeypatch.setenv(key, value)


def test_parses_required_values_and_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_env(monkeypatch)
    settings = Settings(_env_file=None)  # type: ignore[call-arg]
    assert settings.odoo_url == "https://odoo.example.com"
    assert settings.odoo_db == "prod"
    assert settings.odoo_protocol == "jsonrpc"
    assert settings.odoo_timeout_seconds == 10.0
    assert settings.odoo_max_retries == 2
    assert settings.odoo_company_id is None
    assert settings.connector_api_key is None
    assert settings.log_level == "INFO"


def test_secrets_are_masked(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_env(monkeypatch, CONNECTOR_API_KEY="conn-key-0123456789")
    settings = Settings(_env_file=None)  # type: ignore[call-arg]
    assert isinstance(settings.odoo_api_key, SecretStr)
    assert settings.odoo_api_key.get_secret_value() == "key-1234567890123456"
    assert "key-1234567890123456" not in repr(settings)
    assert "hook-secret-0123456" not in repr(settings)
    assert settings.connector_api_key is not None
    assert "conn-key-0123456789" not in str(settings.connector_api_key)


def test_protocol_must_be_known(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_env(monkeypatch, ODOO_PROTOCOL="soap")
    with pytest.raises(ValidationError):
        Settings(_env_file=None)  # type: ignore[call-arg]


def test_company_and_retry_parsing(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_env(monkeypatch, ODOO_COMPANY_ID="3", ODOO_MAX_RETRIES="5", ODOO_PROTOCOL="xmlrpc")
    settings = Settings(_env_file=None)  # type: ignore[call-arg]
    assert settings.odoo_company_id == 3
    assert settings.odoo_max_retries == 5
    assert settings.odoo_protocol == "xmlrpc"


def test_empty_optional_values_become_none(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_env(monkeypatch, ODOO_COMPANY_ID="", CONNECTOR_API_KEY="")
    settings = Settings(_env_file=None)  # type: ignore[call-arg]
    assert settings.odoo_company_id is None
    assert settings.connector_api_key is None


def test_get_settings_is_cached(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_env(monkeypatch)
    assert get_settings() is get_settings()


@pytest.mark.parametrize("name", ["CONNECTOR_API_KEY", "WEBHOOK_SECRET"])
def test_short_secrets_are_rejected(monkeypatch: pytest.MonkeyPatch, name: str) -> None:
    _set_env(monkeypatch, **{name: "x" * 15})
    with pytest.raises(ValidationError) as info:
        Settings(_env_file=None)  # type: ignore[call-arg]
    assert "x" * 15 not in str(info.value)


@pytest.mark.parametrize("name", ["CONNECTOR_API_KEY", "WEBHOOK_SECRET"])
def test_secrets_of_minimum_length_are_accepted(monkeypatch: pytest.MonkeyPatch, name: str) -> None:
    _set_env(monkeypatch, **{name: "x" * 16})
    Settings(_env_file=None)  # type: ignore[call-arg]


def test_idempotency_db_path_defaults_to_the_data_directory(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_env(monkeypatch)
    assert Settings(_env_file=None).idempotency_db_path == "./data/idempotency.sqlite3"  # type: ignore[call-arg]


def test_short_odoo_api_key_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_env(monkeypatch, ODOO_API_KEY="k" * 15)
    with pytest.raises(ValidationError) as info:
        Settings(_env_file=None)  # type: ignore[call-arg]
    assert "k" * 15 not in str(info.value)


def test_odoo_api_key_of_minimum_length_is_accepted(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_env(monkeypatch, ODOO_API_KEY="k" * 16)
    Settings(_env_file=None)  # type: ignore[call-arg]


def test_idempotency_maintenance_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_env(monkeypatch)
    settings = Settings(_env_file=None)  # type: ignore[call-arg]
    assert settings.idempotency_in_progress_timeout_seconds == 300
    assert settings.idempotency_ttl_hours == 24
    assert settings.idempotency_purge_interval_seconds == 3600
