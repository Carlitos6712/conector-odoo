"""Translate Odoo faults (JSON-RPC, XML-RPC, HTTP) into domain errors.

Mapping rules:

* ``AccessDenied``, ``SessionExpiredException``, HTTP 401 -> ``OdooAuthError`` (bad credentials,
  API key or expired session; the client may re-authenticate and replay).
* ``AccessError``, HTTP 403, XML-RPC fault code 4 -> ``OdooPermissionError`` (403). The user is
  authenticated but lacks rights; this is raised during execution, so it is never replayed.
* ``MissingError`` -> ``OdooNotFound``.
* ``ValidationError`` / ``UserError`` / database integrity errors -> ``OdooValidationError``.
* Anything else (unknown faults, other database errors, 5xx) -> ``OdooUnavailable`` (502).

Messages never include Odoo debug traces and are scrubbed of known secrets.
"""

import re
from collections.abc import Iterable, Mapping
from typing import Any

from conector_odoo.domain.errors import (
    ConnectorError,
    OdooAuthError,
    OdooNotFound,
    OdooPermissionError,
    OdooUnavailable,
    OdooValidationError,
)

MAX_MESSAGE_LENGTH = 500
_MASK = "***"

# Odoo XML-RPC fault codes (odoo/http.py).
_FAULT_WARNING = 2
_FAULT_ACCESS_DENIED = 3
_FAULT_ACCESS_ERROR = 4

_EXCEPTION_NAME = re.compile(r"((?:odoo\.exceptions|psycopg2)(?:\.\w+)+)")
_MISSING_HINTS = ("does not exist", "has been deleted", "doesn't exist")


def sanitize(text: str, secrets: Iterable[str] = ()) -> str:
    """Mask secrets and bound the length of a message coming from Odoo."""
    for secret in secrets:
        if secret:
            text = text.replace(secret, _MASK)
    return text[:MAX_MESSAGE_LENGTH]


def map_odoo_exception(name: str | None, message: str) -> ConnectorError:
    """Map an Odoo exception class name (``odoo.exceptions.X``) to a domain error."""
    short = (name or "").rsplit(".", 1)[-1]
    if short in {"AccessDenied", "SessionExpiredException"}:
        return OdooAuthError(message)
    if short == "AccessError":
        return OdooPermissionError(message)
    if short == "MissingError":
        return OdooNotFound(message)
    if short in {"ValidationError", "UserError", "RedirectWarning"}:
        return OdooValidationError(message)
    if (
        name
        and name.startswith("psycopg2")
        and (
            "Integrity" in short
            or short in {"UniqueViolation", "NotNullViolation", "CheckViolation"}
            or short.endswith("Violation")
        )
    ):
        return OdooValidationError(message)
    return OdooUnavailable(message or "unexpected Odoo failure")


def map_jsonrpc_error(error: Mapping[str, Any], secrets: Iterable[str] = ()) -> ConnectorError:
    """Map the ``error`` member of a JSON-RPC response."""
    data = error.get("data")
    if isinstance(data, Mapping):
        name = data.get("name")
        message = data.get("message") or error.get("message") or "Odoo error"
    else:
        name = None
        message = error.get("message") or "Odoo error"
    return map_odoo_exception(
        name if isinstance(name, str) else None, sanitize(str(message), secrets)
    )


def map_xmlrpc_fault(code: int, text: str, secrets: Iterable[str] = ()) -> ConnectorError:
    """Map an ``xmlrpc.client.Fault`` (code and fault string)."""
    last_line = next((line for line in reversed(text.splitlines()) if line.strip()), text)
    message = sanitize(last_line.strip(), secrets)
    if code == _FAULT_ACCESS_DENIED:
        return OdooAuthError(message)
    if code == _FAULT_ACCESS_ERROR:
        return OdooPermissionError(message)
    names = _EXCEPTION_NAME.findall(text)
    if code == _FAULT_WARNING:
        # UserError subclasses (including MissingError) share this code. Prefer the exception
        # class name; fall back to free-text hints only when the class name is absent.
        if names:
            is_missing = names[-1].rsplit(".", 1)[-1] == "MissingError"
        else:
            is_missing = any(hint in text.lower() for hint in _MISSING_HINTS)
        return OdooNotFound(message) if is_missing else OdooValidationError(message)
    if names:
        return map_odoo_exception(names[-1], message)
    return OdooUnavailable(message or "unexpected Odoo failure")


def map_http_status(status: int, secrets: Iterable[str] = ()) -> ConnectorError:
    """Map a non-success HTTP status returned by the Odoo endpoint."""
    if status == 401:
        return OdooAuthError(sanitize(f"Odoo rejected the request (HTTP {status})", secrets))
    if status == 403:
        return OdooPermissionError(sanitize(f"Odoo forbade the request (HTTP {status})", secrets))
    return OdooUnavailable(sanitize(f"Odoo answered with HTTP {status}", secrets))
