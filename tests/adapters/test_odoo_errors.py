import pytest

from conector_odoo.domain.errors import (
    OdooAuthError,
    OdooNotFound,
    OdooPermissionError,
    OdooUnavailable,
    OdooValidationError,
)
from conector_odoo.infrastructure.odoo.errors import (
    map_http_status,
    map_jsonrpc_error,
    map_xmlrpc_fault,
    sanitize,
)


def _error(name: str, message: str = "boom", debug: str = "") -> dict[str, object]:
    return {
        "code": 200,
        "message": "Odoo Server Error",
        "data": {"name": name, "message": message, "debug": debug},
    }


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("odoo.exceptions.AccessDenied", OdooAuthError),
        ("odoo.exceptions.AccessError", OdooPermissionError),
        ("odoo.http.SessionExpiredException", OdooAuthError),
        ("odoo.exceptions.MissingError", OdooNotFound),
        ("odoo.exceptions.ValidationError", OdooValidationError),
        ("odoo.exceptions.UserError", OdooValidationError),
        ("psycopg2.IntegrityError", OdooValidationError),
        ("psycopg2.errors.UniqueViolation", OdooValidationError),
        ("psycopg2.OperationalError", OdooUnavailable),
        ("builtins.KeyError", OdooUnavailable),
    ],
)
def test_jsonrpc_error_names_map_to_domain_errors(name: str, expected: type[Exception]) -> None:
    assert type(map_jsonrpc_error(_error(name))) is expected


def test_jsonrpc_error_without_data_is_unavailable() -> None:
    assert isinstance(map_jsonrpc_error({"code": -32000, "message": "weird"}), OdooUnavailable)


def test_messages_never_include_secrets_or_debug_traces() -> None:
    error = map_jsonrpc_error(
        _error("odoo.exceptions.UserError", "bad key-123 value", debug="Traceback key-123"),
        secrets=["key-123"],
    )
    assert "key-123" not in str(error)
    assert "Traceback" not in str(error)


def test_sanitize_masks_and_truncates() -> None:
    assert sanitize("a secret b", ["secret"]) == "a *** b"
    assert len(sanitize("x" * 5000, [])) <= 500
    assert sanitize("keep", [""]) == "keep"


@pytest.mark.parametrize(
    ("code", "text", "expected"),
    [
        (3, "Access Denied", OdooAuthError),
        (4, "You are not allowed", OdooPermissionError),
        (2, "Record does not exist or has been deleted.", OdooNotFound),
        (2, "Invalid field value", OdooValidationError),
        (1, "Traceback...\nodoo.exceptions.MissingError: gone", OdooNotFound),
        (1, "Traceback...\nodoo.exceptions.ValidationError: bad", OdooValidationError),
        (1, "Traceback...\nodoo.exceptions.AccessDenied: no", OdooAuthError),
        (1, "Traceback...\nodoo.exceptions.AccessError: not allowed", OdooPermissionError),
        (
            2,
            "Traceback...\nodoo.exceptions.ValidationError: field 'x' does not exist",
            OdooValidationError,
        ),
        (
            2,
            "Traceback...\nodoo.exceptions.MissingError: Record is gone",
            OdooNotFound,
        ),
        (1, "Traceback...\nKeyError: 'x'", OdooUnavailable),
    ],
)
def test_xmlrpc_faults_map_to_domain_errors(
    code: int, text: str, expected: type[Exception]
) -> None:
    assert type(map_xmlrpc_fault(code, text)) is expected


@pytest.mark.parametrize(
    ("status", "expected"),
    [
        (401, OdooAuthError),
        (403, OdooPermissionError),
        (404, OdooUnavailable),
        (503, OdooUnavailable),
    ],
)
def test_http_status_mapping(status: int, expected: type[Exception]) -> None:
    assert type(map_http_status(status)) is expected
