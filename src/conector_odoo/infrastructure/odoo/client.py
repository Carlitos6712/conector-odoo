"""High-level async Odoo client on top of an ``OdooTransport``."""

import asyncio
from typing import Any

from conector_odoo.domain.errors import OdooAuthError, OdooUnavailable
from conector_odoo.infrastructure.odoo.transport import OdooTransport


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
    """

    def __init__(self, transport: OdooTransport, company_id: int | None = None) -> None:
        self._transport = transport
        self._company_id = company_id
        self._uid: int | None = None
        self._epoch = 0
        self._lock = asyncio.Lock()

    @property
    def uid(self) -> int | None:
        return self._uid

    async def ensure_authenticated(self) -> int:
        if self._uid is not None:
            return self._uid
        async with self._lock:
            if self._uid is None:
                self._uid = await self._transport.authenticate()
                self._epoch += 1
            return self._uid

    async def _reauthenticate(self, seen_epoch: int) -> None:
        async with self._lock:
            if self._epoch != seen_epoch:
                return  # another caller already refreshed the session
            self._uid = None
            self._uid = await self._transport.authenticate()
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
            return await self._transport.execute_kw(model, method, args, final_kwargs)
        except OdooAuthError:
            await self._reauthenticate(epoch)
            return await self._transport.execute_kw(model, method, args, final_kwargs)

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

    async def check(self) -> dict[str, Any]:
        """Health probe: verifies Odoo is reachable and the credentials are valid."""
        async with self._lock:
            self._uid = await self._transport.authenticate()
            self._epoch += 1
            return {"status": "ok", "uid": self._uid}

    async def aclose(self) -> None:
        await self._transport.aclose()
