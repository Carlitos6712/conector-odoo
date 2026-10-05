"""Serve the built admin frontend (Vite ``dist``) with a single-page-app fallback.

The catch-all is registered AFTER every API router, so a real route always wins. Paths whose first
segment belongs to the API (any registered route, plus the docs and admin prefixes) are never
answered with HTML: an unknown ``/admin/api/x`` stays a JSON 404. Files are resolved strictly
inside the dist directory (symlinks and ``..`` cannot escape it) and read per request, so a build
produced after startup is picked up without a restart.
"""

import logging
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, Response

logger = logging.getLogger(__name__)

INDEX_NAME = "index.html"
# Vite emits content-hashed files under ``assets/``: safe to cache forever.
IMMUTABLE_PREFIX = "assets/"
IMMUTABLE = "public, max-age=31536000, immutable"
REVALIDATE = "no-cache"
# Prefixes that belong to the API even when no route is defined for the exact path.
RESERVED_PREFIXES = frozenset({"admin", "docs", "redoc", "openapi.json", "webhooks"})


def _api_prefixes(app: FastAPI) -> frozenset[str]:
    prefixes = set(RESERVED_PREFIXES)
    for route in app.routes:
        first = getattr(route, "path", "").strip("/").split("/", 1)[0]
        if first and not first.startswith("{"):
            prefixes.add(first)
    return frozenset(prefixes)


def _resolve_file(root: Path, relative: str) -> Path | None:
    """The file for ``relative`` if it exists inside ``root`` (symlinks resolved), else None."""
    if "\x00" in relative or any(part == ".." for part in relative.replace("\\", "/").split("/")):
        return None
    try:
        candidate = (root / relative).resolve()
        if candidate.is_file() and candidate.is_relative_to(root):
            return candidate
    except (OSError, ValueError):
        pass
    return None


def mount_frontend(app: FastAPI, dist_dir: str) -> None:
    root = Path(dist_dir).resolve()
    if not (root / INDEX_NAME).is_file():
        logger.warning(
            "frontend build not found at %s; the admin UI is not served (run the frontend build)",
            root,
        )
    reserved = _api_prefixes(app)

    async def serve(path: str, request: Request) -> Response:
        first = path.split("/", 1)[0]
        if request.method not in ("GET", "HEAD") or first in reserved:
            raise HTTPException(status_code=404)
        file = _resolve_file(root, path) if path else None
        if file is not None:
            cache = IMMUTABLE if path.startswith(IMMUTABLE_PREFIX) else REVALIDATE
            return FileResponse(file, headers={"Cache-Control": cache})
        if "." in path.rsplit("/", 1)[-1]:  # a missing asset must not come back as HTML
            raise HTTPException(status_code=404)
        index = _resolve_file(root, INDEX_NAME)
        if index is None:
            raise HTTPException(status_code=404)
        return FileResponse(index, headers={"Cache-Control": REVALIDATE})

    # Every method is routed here so unknown non-GET paths keep answering 404 (not 405).
    app.add_api_route(
        "/{path:path}",
        serve,
        methods=["GET", "HEAD", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        include_in_schema=False,
    )
