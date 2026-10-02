"""NDJSON streaming responses for exports.

One JSON object per line (``application/x-ndjson``). The first batch is fetched *before* the
response is created, so a failure at that point (auth, permission, validation, Odoo down) is
mapped by the normal error handlers to a proper status. After the first byte the status line is
already sent, so a later failure cannot change it: the stream ends with a final line
``{"error": "<code>", "detail": "<scrubbed message>"}`` and the failure is logged. Clients must
treat a last line with an ``error`` key as a failed (incomplete) export.
"""

import json
import logging
from collections.abc import AsyncIterator, Callable
from typing import Any, TypeVar

from fastapi import Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from conector_odoo.domain.errors import ConnectorError
from conector_odoo.infrastructure.api.errors import error_status_and_code, scrub

logger = logging.getLogger(__name__)

T = TypeVar("T")

NDJSON_MEDIA_TYPE = "application/x-ndjson"


def _encode(rows: list[T], serialize: Callable[[T], BaseModel]) -> bytes:
    return "".join(serialize(row).model_dump_json() + "\n" for row in rows).encode()


async def _aclose(batches: AsyncIterator[Any]) -> None:
    close = getattr(batches, "aclose", None)
    if close is not None:
        await close()


async def _stream(
    first: list[T],
    batches: AsyncIterator[list[T]],
    serialize: Callable[[T], BaseModel],
    request: Request,
) -> AsyncIterator[bytes]:
    try:
        yield _encode(first, serialize)
        async for batch in batches:
            yield _encode(batch, serialize)
    except Exception as exc:  # the status is already sent; report in-band (cancellation passes)
        if isinstance(exc, ConnectorError):
            _, code = error_status_and_code(exc)
            detail = scrub(str(exc), request.app.state.settings)
        else:
            code, detail = "internal_error", "export failed"
        logger.warning(
            "export failed mid-stream",
            extra={
                "error_type": type(exc).__name__,
                "path": request.url.path,
                "detail": detail,
                "request_id": getattr(request.state, "request_id", None),
            },
        )
        yield _line({"error": code, "detail": detail})
    finally:
        await _aclose(batches)


def _line(payload: dict[str, str]) -> bytes:
    return (json.dumps(payload, ensure_ascii=False) + "\n").encode()


async def ndjson_response(
    batches: AsyncIterator[list[T]],
    serialize: Callable[[T], BaseModel],
    request: Request,
    filename: str,
) -> StreamingResponse:
    """Build the streaming response; raises (normal error mapping) if the first batch fails."""
    try:
        first: list[T] = await anext(batches, [])
    except BaseException:
        await _aclose(batches)
        raise
    return StreamingResponse(
        _stream(first, batches, serialize, request),
        media_type=NDJSON_MEDIA_TYPE,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
