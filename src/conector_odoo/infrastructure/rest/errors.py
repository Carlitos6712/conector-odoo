"""Normalization of HTTP failures into domain errors. Messages carry the status and a short,
scrubbed snippet of the body, never headers or credentials."""

import re
from collections.abc import Iterable
from typing import Any

import httpx

from conector_odoo.domain.errors import (
    ConnectorError,
    RecordRejected,
    RemoteAuthError,
    RemoteUnavailable,
    ResourceNotFound,
)

SNIPPET_LIMIT = 200
_LOC_NOISE = {"body", "query", "path", "header"}


def snippet(text: str, secrets: Iterable[str] = ()) -> str:
    for secret in secrets:
        if secret:
            text = text.replace(secret, "***")
    text = re.sub(r"\s+", " ", text).strip()
    return text[:SNIPPET_LIMIT] + ("..." if len(text) > SNIPPET_LIMIT else "")


def error_for(response: httpx.Response, where: str, secrets: Iterable[str] = ()) -> ConnectorError:
    """Domain error for a non-2xx ``response`` of the request described by ``where``."""
    status = response.status_code
    body = _json(response)
    text = snippet(response.text, secrets)
    prefix = f"{where}: HTTP {status}"
    if status in (401, 403):
        return RemoteAuthError(f"{prefix} (credentials rejected or not allowed)")
    if status == 404:
        return ResourceNotFound(f"{prefix} (not found)")
    if status in (400, 409, 422):
        fields = {k: snippet(v, secrets) for k, v in field_errors(body).items()}
        message = snippet(_message(body), secrets) or text
        return RecordRejected(f"{prefix}: {message}", fields)
    return RemoteUnavailable(f"{prefix}: {text}" if text else prefix)


def _json(response: httpx.Response) -> Any:
    try:
        return response.json()
    except ValueError:
        return None


def _message(body: Any) -> str:
    if isinstance(body, dict):
        for key in ("message", "detail", "error", "title"):
            if isinstance(body.get(key), str):
                return str(body[key])
    return ""


def field_errors(body: Any) -> dict[str, str]:
    """Field -> message from the common validation shapes (FastAPI ``detail``, ``errors`` map or
    list)."""
    if not isinstance(body, dict):
        return {}
    found: dict[str, str] = {}
    detail = body.get("detail")
    if isinstance(detail, list):
        for item in detail:
            if isinstance(item, dict) and isinstance(item.get("msg"), str):
                loc = [str(p) for p in item.get("loc", []) if str(p) not in _LOC_NOISE]
                if loc:
                    found[".".join(loc)] = item["msg"]
    errors = body.get("errors")
    if isinstance(errors, dict):
        for name, value in errors.items():
            found[str(name)] = _join(value)
    elif isinstance(errors, list):
        for item in errors:
            if isinstance(item, dict) and item.get("field") and item.get("message"):
                found[str(item["field"])] = str(item["message"])
    return found


def _join(value: Any) -> str:
    if isinstance(value, list):
        return "; ".join(str(v) for v in value)
    return str(value)
