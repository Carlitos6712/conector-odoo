"""In-memory ``RecordEndpoint`` (source + sink) shared by sync/mapping tests."""

from collections.abc import AsyncIterator, Callable
from typing import Any

from conector_odoo.domain.errors import ConnectorError, ResourceNotFound
from conector_odoo.domain.records import Record, RecordFilter, ResourceSchema


class InMemoryRecordEndpoint:
    def __init__(self, schemas: dict[str, ResourceSchema] | None = None) -> None:
        self.schemas = dict(schemas or {})
        self.records: dict[str, dict[str, Record]] = {name: {} for name in self.schemas}
        self.create_calls = 0
        self.update_calls = 0
        self.delete_calls = 0
        self.get_calls = 0
        self._hooks: list[Callable[[str, str, dict[str, Any]], BaseException | None]] = []
        self._next_id = 1
        self._replays: dict[tuple[str, str], Record] = {}
        self._rejections: list[ConnectorError] = []

    def seed(self, resource: str, fields: dict[str, Any]) -> Record:
        record = Record(id=str(self._next_id), fields=fields)
        self._next_id += 1
        self._table(resource)[record.id or ""] = record
        return record

    def reject_next(self, error: ConnectorError) -> None:
        """Make the next ``create``/``update`` raise ``error`` (once)."""
        self._rejections.append(error)

    def reject_when(self, hook: Callable[[str, str, dict[str, Any]], BaseException | None]) -> None:
        """Persistent rule: ``hook(operation, resource, fields)`` returns an exception to raise
        for a ``create``/``update`` (any ``BaseException``, e.g. a simulated crash) or ``None``."""
        self._hooks.append(hook)

    def _check_hooks(self, operation: str, resource: str, fields: dict[str, Any]) -> None:
        for hook in self._hooks:
            error = hook(operation, resource, fields)
            if error is not None:
                raise error

    def _table(self, resource: str) -> dict[str, Record]:
        if resource not in self.schemas:
            raise ResourceNotFound(resource)
        return self.records[resource]

    async def describe(self, resource: str) -> ResourceSchema:
        if resource not in self.schemas:
            raise ResourceNotFound(resource)
        return self.schemas[resource]

    async def iter_batches(
        self, resource: str, record_filter: RecordFilter, batch_size: int
    ) -> AsyncIterator[list[Record]]:
        if batch_size < 1:
            raise ValueError("batch_size must be >= 1")
        matching = [
            r
            for r in self._table(resource).values()
            if all(r.get(k) == v for k, v in record_filter.equals.items())
        ]
        for start in range(0, len(matching), batch_size):
            yield matching[start : start + batch_size]

    async def get(self, resource: str, id: str) -> Record | None:
        self.get_calls += 1
        return self._table(resource).get(id)

    async def sample(self, resource: str, limit: int) -> list[Record]:
        return list(self._table(resource).values())[:limit]

    async def find_by(self, resource: str, field: str, value: Any) -> Record | None:
        return next((r for r in self._table(resource).values() if r.get(field) == value), None)

    async def create(self, resource: str, fields: dict[str, Any], idempotency_key: str) -> Record:
        self.create_calls += 1
        self._table(resource)  # unknown resource -> ResourceNotFound
        self._check_hooks("create", resource, fields)
        if self._rejections:
            raise self._rejections.pop(0)
        replay = self._replays.get((resource, idempotency_key))
        if replay is not None:
            return replay
        record = self.seed(resource, fields)
        self._replays[(resource, idempotency_key)] = record
        return record

    async def update(self, resource: str, id: str, fields: dict[str, Any]) -> Record:
        self.update_calls += 1
        table = self._table(resource)
        self._check_hooks("update", resource, fields)
        if self._rejections:
            raise self._rejections.pop(0)
        current = table.get(id)
        if current is None:
            raise ResourceNotFound(f"{resource}/{id}")
        updated = Record(id=id, fields={**current.fields, **fields})
        table[id] = updated
        return updated

    async def delete(self, resource: str, id: str) -> None:
        self.delete_calls += 1
        table = self._table(resource)
        if id not in table:
            raise ResourceNotFound(f"{resource}/{id}")
        del table[id]
