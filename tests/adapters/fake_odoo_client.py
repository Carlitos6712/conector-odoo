"""Recording fake with the ``OdooClient`` surface used by the repository adapters."""

from collections.abc import AsyncIterator
from typing import Any


class FakeOdooClient:
    """Scripted responses per ``(model, method)``; every call is recorded in ``calls``."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, str, dict[str, Any]]] = []
        self.responses: dict[tuple[str, str], list[Any]] = {}

    def script(self, model: str, method: str, *results: Any) -> None:
        self.responses.setdefault((model, method), []).extend(results)

    def _call(self, model: str, method: str, **params: Any) -> Any:
        self.calls.append((model, method, params))
        queue = self.responses.get((model, method))
        if not queue:
            raise AssertionError(f"unscripted call {model}.{method} {params}")
        item = queue.pop(0)
        if isinstance(item, BaseException):
            raise item
        return item

    def calls_to(self, model: str, method: str) -> list[dict[str, Any]]:
        return [p for m, meth, p in self.calls if (m, meth) == (model, method)]

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
        return self._call(  # type: ignore[no-any-return]
            model,
            "search_read",
            domain=domain,
            fields=fields,
            limit=limit,
            offset=offset,
            order=order,
            company_id=company_id,
        )

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
        """Scripted per ``(model, "iter_search_read")``: every scripted item is one batch."""
        self.calls.append(
            (
                model,
                "iter_search_read",
                {"domain": domain, "fields": fields, "batch_size": batch_size},
            )
        )
        queue = self.responses.get((model, "iter_search_read"))
        if queue is None:
            raise AssertionError(f"unscripted call {model}.iter_search_read")
        batches = list(queue)
        queue.clear()
        for item in batches:
            if isinstance(item, BaseException):
                raise item
            yield item

    async def read(
        self,
        model: str,
        ids: list[int],
        fields: list[str] | None = None,
        *,
        company_id: int | None = None,
        context: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        return self._call(  # type: ignore[no-any-return]
            model, "read", ids=ids, fields=fields, company_id=company_id
        )

    async def create(
        self,
        model: str,
        values: dict[str, Any],
        *,
        company_id: int | None = None,
        context: dict[str, Any] | None = None,
    ) -> int:
        return self._call(  # type: ignore[no-any-return]
            model, "create", values=values, company_id=company_id
        )

    async def write(
        self,
        model: str,
        ids: list[int],
        values: dict[str, Any],
        *,
        company_id: int | None = None,
        context: dict[str, Any] | None = None,
    ) -> bool:
        return self._call(model, "write", ids=ids, values=values)  # type: ignore[no-any-return]

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
        return self._call(model, method, args=args, kwargs=kwargs, company_id=company_id)
