import asyncio
import logging

import pytest

from conector_odoo.infrastructure.idempotency.purge import purge_loop


class RecordingStore:
    def __init__(self, fail_first: bool = False) -> None:
        self.calls: list[float] = []
        self.fail_first = fail_first
        self.ran = asyncio.Event()

    async def purge_older_than(self, hours: float) -> int:
        self.calls.append(hours)
        self.ran.set()
        if self.fail_first and len(self.calls) == 1:
            raise RuntimeError("disk gone")
        return 2


async def test_purges_at_startup_and_then_every_interval() -> None:
    store = RecordingStore()
    task = asyncio.create_task(purge_loop(store, ttl_hours=24, interval_seconds=0.01))  # type: ignore[arg-type]
    await asyncio.sleep(0.1)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert len(store.calls) >= 3
    assert set(store.calls) == {24}


async def test_a_failing_purge_is_logged_and_the_loop_keeps_running(
    caplog: pytest.LogCaptureFixture,
) -> None:
    store = RecordingStore(fail_first=True)
    with caplog.at_level(logging.ERROR):
        task = asyncio.create_task(purge_loop(store, ttl_hours=1, interval_seconds=0.01))  # type: ignore[arg-type]
        await asyncio.sleep(0.1)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    assert len(store.calls) >= 2
    assert any("purge" in r.getMessage() for r in caplog.records)
