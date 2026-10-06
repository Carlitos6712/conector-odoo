"""The ODOO_* connection variables are optional (legacy mode needs all four)."""

import pytest

from conector_odoo.config import Settings


def settings(**values: str) -> Settings:
    return Settings(_env_file=None, webhook_secret="whsec-test-secret-123", **values)  # type: ignore[call-arg,arg-type]


def test_no_odoo_variable_is_required(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ("ODOO_URL", "ODOO_DB", "ODOO_USER", "ODOO_API_KEY"):
        monkeypatch.delenv(name, raising=False)
    built = settings()
    assert built.odoo_url is None and built.odoo_api_key is None
    assert not built.odoo_env_configured()
    assert not built.odoo_env_partial()


def test_empty_values_from_compose_count_as_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    # docker-compose passes unset optional variables as empty strings.
    for name in ("ODOO_URL", "ODOO_DB", "ODOO_USER", "ODOO_API_KEY"):
        monkeypatch.setenv(name, "")
    assert not settings().odoo_env_configured()


def test_all_four_make_the_env_connection_complete() -> None:
    built = settings(odoo_url="https://o.test", odoo_db="d", odoo_user="u", odoo_api_key="k" * 20)
    assert built.odoo_env_configured()
    assert not built.odoo_env_partial()


def test_a_partial_configuration_is_reported_and_unusable() -> None:
    built = settings(odoo_url="https://o.test", odoo_db="d")
    assert built.odoo_env_partial()
    assert not built.odoo_env_configured()


def test_a_short_api_key_is_still_rejected() -> None:
    with pytest.raises(ValueError, match="at least 16"):
        settings(odoo_api_key="short")
