"""High-level async Odoo client on top of an ``OdooTransport``."""

import asyncio
from collections.abc import AsyncIterator
from typing import Any, TypeVar

from conector_odoo.application.pagination import (
    DEFAULT_MAX_CONCURRENCY,
    MAX_BATCH_SIZE,
)
from conector_odoo.domain.errors import (
    BatchPartiallyApplied,
    ConnectorError,
    OdooAuthError,
    OdooUnavailable,
    OdooValidationError,
)
from conector_odoo.infrastructure.odoo.transport import OdooTransport

T = TypeVar("T")


class OdooClient:
    """Authenticates lazily, caches the uid and recovers from expired credentials.

    * The uid is authenticated once (guarded by a lock so concurrent first calls do not
      authenticate twice) and cached on the client; the transport keeps the session state it
      needs (see ``OdooTransport``).
    * On ``OdooAuthError`` (bad/expired credentials or session) during a call the client
      re-authenticates once and retries that call once. Replaying even ``create`` is safe here
      because an auth failure means Odoo rejected the call before executing it. Concurrent
      failures share a single re-authentication. ``OdooPermissionError`` (``AccessError``,
      HTTP 403) is raised during execution, so it propagates immediately and is never replayed.
    * ``company_id`` (constructor default, overridable per call) is injected into the call
      ``context`` as ``allowed_company_ids`` and ``company_id``; an explicitly provided
      context wins on key conflicts.
    * At most ``max_concurrency`` transport calls are in flight at once (an ``asyncio.Semaphore``
      held only for the duration of one call, never across a re-authentication, so a single slot
      cannot deadlock).
    * Batch helpers (``iter_search_read``, ``read_many``, ``create_many``, ``write_many``) keep
      memory and request size bounded for large volumes; see each method.
    """

    def __init__(
        self,
        transport: OdooTransport,
        company_id: int | None = None,
        max_concurrency: int = DEFAULT_MAX_CONCURRENCY,
    ) -> None:
        if max_concurrency < 1:
            raise ValueError("max_concurrency must be at least 1")
        self._transport = transport
        self._company_id = company_id
        self._max_concurrency = max_concurrency
        self._slots = asyncio.Semaphore(max_concurrency)
        self._uid: int | None = None
        self._epoch = 0
        self._lock = asyncio.Lock()

    @property
    def uid(self) -> int | None:
        return self._uid

    async def _authenticate(self) -> int:
        async with self._slots:
            return await self._transport.authenticate()

    async def _send(self, model: str, method: str, args: list[Any], kwargs: dict[str, Any]) -> Any:
        async with self._slots:
            return await self._transport.execute_kw(model, method, args, kwargs)

    async def ensure_authenticated(self) -> int:
        if self._uid is not None:
            return self._uid
        async with self._lock:
            if self._uid is None:
                self._uid = await self._authenticate()
                self._epoch += 1
            return self._uid

    async def _reauthenticate(self, seen_epoch: int) -> None:
        async with self._lock:
            if self._epoch != seen_epoch:
                return  # another caller already refreshed the session
            self._uid = None
            self._uid = await self._authenticate()
            self._epoch += 1

    def _build_kwargs(
        self,
        kwargs: dict[str, Any] | None,
        company_id: int | None,
        context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        result = dict(kwargs or {})
        merged: dict[str, Any] = dict(result.get("context") or {})
        if context:
            merged.update(context)
        effective = company_id if company_id is not None else self._company_id
        if effective is not None:
            merged = {"allowed_company_ids": [effective], "company_id": effective, **merged}
        if merged:
            result["context"] = merged
        return result

    async def execute_kw(
        self,
        model: str,
        method: str,
        args: list[Any],
        kwargs: dict[str, Any] | None = None,
        *,
        company_id: int | None = None,
        context: dict[str, Any] | None = None,
    ) -> Any:
        await self.ensure_authenticated()
        epoch = self._epoch
        final_kwargs = self._build_kwargs(kwargs, company_id, context)
        try:
            return await self._send(model, method, args, final_kwargs)
        except OdooAuthError:
            await self._reauthenticate(epoch)
            return await self._send(model, method, args, final_kwargs)

    async def search_read(
        self,
        model: str,
        domain: list[Any],
        fields: list[str] | None = None,
        limit: int | None = None,
        offset: int = 0,
        order: str | None = None,
        *,
        company_id: int | None = None,
        context: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        kwargs: dict[str, Any] = {}
        if fields is not None:
            kwargs["fields"] = fields
        if limit is not None:
            kwargs["limit"] = limit
        if offset:
            kwargs["offset"] = offset
        if order is not None:
            kwargs["order"] = order
        result = await self.execute_kw(
            model, "search_read", [domain], kwargs, company_id=company_id, context=context
        )
        return list(result)

    async def read(
        self,
        model: str,
        ids: list[int],
        fields: list[str] | None = None,
        *,
        company_id: int | None = None,
        context: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        kwargs = {"fields": fields} if fields is not None else {}
        result = await self.execute_kw(
            model, "read", [ids], kwargs, company_id=company_id, context=context
        )
        return list(result)

    async def create(
        self,
        model: str,
        values: dict[str, Any],
        *,
        company_id: int | None = None,
        context: dict[str, Any] | None = None,
    ) -> int:
        result = await self.execute_kw(
            model, "create", [values], company_id=company_id, context=context
        )
        created = result[0] if isinstance(result, list) and result else result
        if isinstance(created, bool) or not isinstance(created, int):
            raise OdooUnavailable(f"unexpected response creating {model}")
        return created

    async def write(
        self,
        model: str,
        ids: list[int],
        values: dict[str, Any],
        *,
        company_id: int | None = None,
        context: dict[str, Any] | None = None,
    ) -> bool:
        result = await self.execute_kw(
            model, "write", [ids, values], company_id=company_id, context=context
        )
        return bool(result)

    async def unlink(
        self,
        model: str,
        ids: list[int],
        *,
        company_id: int | None = None,
        context: dict[str, Any] | None = None,
    ) -> bool:
        """Soft delete: archive the records (``active=False``) instead of removing them."""
        return await self.write(
            model, ids, {"active": False}, company_id=company_id, context=context
        )

    async def search_count(
        self,
        model: str,
        domain: list[Any],
        *,
        company_id: int | None = None,
        context: dict[str, Any] | None = None,
    ) -> int:
        result = await self.execute_kw(
            model, "search_count", [domain], company_id=company_id, context=context
        )
        return int(result)

    async def iter_search_read(
        self,
        model: str,
        domain: list[Any],
        fields: list[str] | None = None,
        *,
        batch_size: int = 500,
        company_id: int | None = None,
        context: dict[str, Any] | None = None,
    ) -> AsyncIterator[list[dict[str, Any]]]:
        """Yield ``search_read`` results in batches using keyset pagination on ``id``.

        Every batch is ``search_read(domain + [id > last_id], limit=batch_size, order="id asc")``,
        so the cost of a batch does not grow with its position (offset pagination rescans the
        skipped rows) and rows inserted or deleted meanwhile cannot shift the window. Iteration
        stops on a short or empty batch; a full last batch costs one extra (empty) call. Only the
        current batch is held in memory.
        """
        _check_size("batch_size", batch_size)
        read_fields = None if fields is None else list(dict.fromkeys([*fields, "id"]))
        last_id: int | None = None
        while True:
            page_domain = list(domain)
            if last_id is not None:
                page_domain.append(["id", ">", last_id])
            rows = await self.search_read(
                model,
                page_domain,
                read_fields,
                limit=batch_size,
                order="id asc",
                company_id=company_id,
                context=context,
            )
            if rows:
                yield rows
            if len(rows) < batch_size:
                return
            last_id = max(int(row["id"]) for row in rows)

    async def read_many(
        self,
        model: str,
        ids: list[int],
        fields: list[str] | None = None,
        *,
        chunk_size: int = 500,
        company_id: int | None = None,
        context: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        """``read`` in chunks; rows follow the order of ``ids`` and missing ids are skipped."""
        _check_size("chunk_size", chunk_size)
        by_id: dict[int, dict[str, Any]] = {}
        for chunk in _chunks(ids, chunk_size):
            for row in await self.read(
                model, chunk, fields, company_id=company_id, context=context
            ):
                by_id[int(row["id"])] = row
        return [by_id[i] for i in ids if i in by_id]

    async def create_many(
        self,
        model: str,
        vals_list: list[dict[str, Any]],
        *,
        chunk_size: int = 100,
        company_id: int | None = None,
        context: dict[str, Any] | None = None,
    ) -> list[int]:
        """Multi-create in chunks; returns the new ids in input order.

        Each chunk is one ``create`` call with a list of dicts. ``create`` is not idempotent, so
        transports never retry it and a failed chunk is not retried here either. If a chunk fails
        after earlier ones succeeded, ``BatchPartiallyApplied`` carries the ids already created
        (the chunk's own outcome is unknown when the error is a timeout: verify in Odoo). A
        failure of the very first chunk re-raises the original error: nothing is known to be
        applied.
        """
        _check_size("chunk_size", chunk_size)
        created: list[int] = []
        for index, chunk in enumerate(_chunks(vals_list, chunk_size)):
            try:
                result = await self.execute_kw(
                    model, "create", [chunk], company_id=company_id, context=context
                )
            except ConnectorError as exc:
                if not created:
                    raise
                raise BatchPartiallyApplied(
                    created, index, f"chunk {index} failed after {len(created)} records: {exc}"
                ) from exc
            ids = _created_ids(model, result, len(chunk))
            created.extend(ids)
        return created

    async def write_many(
        self,
        model: str,
        ids: list[int],
        values: dict[str, Any],
        *,
        chunk_size: int = 500,
        company_id: int | None = None,
        context: dict[str, Any] | None = None,
    ) -> bool:
        """Write the same ``values`` on ``ids`` in chunks; ``True`` when every chunk succeeded."""
        _check_size("chunk_size", chunk_size)
        ok = True
        for chunk in _chunks(ids, chunk_size):
            ok = (
                await self.write(model, chunk, values, company_id=company_id, context=context)
                and ok
            )
        return ok

    async def check(self) -> dict[str, Any]:
        """Health probe: verifies Odoo is reachable and the credentials are valid."""
        async with self._lock:
            self._uid = await self._authenticate()
            self._epoch += 1
            return {"status": "ok", "uid": self._uid}

    async def aclose(self) -> None:
        await self._transport.aclose()


def _check_size(name: str, value: int) -> None:
    if not 1 <= value <= MAX_BATCH_SIZE:
        raise OdooValidationError(f"{name} must be between 1 and {MAX_BATCH_SIZE}")


def _chunks(items: list[T], size: int) -> list[list[T]]:
    return [items[start : start + size] for start in range(0, len(items), size)]


def _created_ids(model: str, result: Any, expected: int) -> list[int]:
    if (
        not isinstance(result, list)
        or len(result) != expected
        or any(isinstance(i, bool) or not isinstance(i, int) for i in result)
    ):
        raise OdooUnavailable(f"unexpected response creating {model} records")
    return [int(i) for i in result]
