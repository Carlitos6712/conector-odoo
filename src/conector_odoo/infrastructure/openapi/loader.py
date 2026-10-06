"""Fetch and parse an OpenAPI 3.x / Swagger 2.0 document (JSON or YAML) defensively.

Only http/https URLs are fetched, the download is streamed against a size cap, YAML goes through
``safe_load`` only and nothing referenced from inside the document is ever fetched.
"""

import json
from collections.abc import Mapping
from typing import Any
from urllib.parse import urlsplit

import httpx
import yaml

from conector_odoo.domain.errors import OpenApiImportError

MAX_BYTES = 5 * 1024 * 1024
DEFAULT_TIMEOUT = 15.0
_MAX_REDIRECTS = 3


async def fetch_document(
    url: str,
    *,
    tls_verify: bool = True,
    headers: Mapping[str, str] | None = None,
    timeout_seconds: float = DEFAULT_TIMEOUT,
    max_bytes: int = MAX_BYTES,
) -> bytes:
    """Download ``url`` (http/https only). ``headers`` are sent only when the caller passes them."""
    parts = urlsplit(url.strip())
    if parts.scheme not in ("http", "https") or not parts.hostname:
        raise OpenApiImportError("the document URL must be an http or https URL")
    try:
        async with (
            httpx.AsyncClient(
                verify=tls_verify,
                timeout=timeout_seconds,
                headers=dict(headers) if headers else None,
                follow_redirects=True,
                max_redirects=_MAX_REDIRECTS,
            ) as client,
            client.stream("GET", url.strip()) as response,
        ):
            if response.status_code >= 400:
                raise OpenApiImportError(f"the server answered HTTP {response.status_code}")
            declared = response.headers.get("content-length", "")
            if declared.isdigit() and int(declared) > max_bytes:
                raise _too_large(max_bytes)
            body = bytearray()
            async for chunk in response.aiter_bytes():
                body.extend(chunk)
                if len(body) > max_bytes:
                    raise _too_large(max_bytes)
            return bytes(body)
    except (httpx.HTTPError, httpx.InvalidURL) as exc:
        raise OpenApiImportError(f"cannot reach the document URL ({type(exc).__name__})") from None


def load_document(content: bytes | str, *, max_bytes: int = MAX_BYTES) -> dict[str, Any]:
    """Parse JSON or YAML into a dict and check it is an OpenAPI 3.x or Swagger 2.0 document."""
    raw = content.encode() if isinstance(content, str) else content
    if len(raw) > max_bytes:
        raise _too_large(max_bytes)
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise OpenApiImportError("the document is not valid UTF-8 text") from None
    if not text.strip():
        raise OpenApiImportError("the document is empty")
    try:
        data = json.loads(text)
    except ValueError:
        try:
            data = yaml.safe_load(text)
        except yaml.YAMLError:
            raise OpenApiImportError("the document is neither valid JSON nor valid YAML") from None
    if not isinstance(data, dict):
        raise OpenApiImportError("the document must be a JSON/YAML object")
    version = str(data.get("openapi", ""))
    if not (version.startswith("3.") or str(data.get("swagger", "")) == "2.0"):
        raise OpenApiImportError("only OpenAPI 3.x and Swagger 2.0 documents are supported")
    return data


def _too_large(max_bytes: int) -> OpenApiImportError:
    return OpenApiImportError(f"the document is larger than the {max_bytes} byte limit")
