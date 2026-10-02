import logging
import time
import uuid
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from conector_odoo.domain.events import OdooEvent
from conector_odoo.infrastructure.webhooks.signature import sign
from tests.api.conftest import API_KEY, Env, build_env, make_settings

SECRET = "whsec-test-secret-123"
URL = "/webhooks/odoo"
MAX_BODY = 1024 * 1024


def payload(**overrides: Any) -> dict[str, Any]:
    body: dict[str, Any] = {
        "event_id": str(uuid.uuid4()),
        "event_type": "partner.created",
        "model": "res.partner",
        "record_id": 7,
        "occurred_at": datetime.now(UTC).isoformat(),
        "payload": {"name": "Ada"},
    }
    body.update(overrides)
    return body


def encode(body: dict[str, Any]) -> bytes:
    import json

    return json.dumps(body).encode()


def signed_headers(raw: bytes, *, secret: str = SECRET, ts: int | None = None) -> dict[str, str]:
    stamp = int(time.time()) if ts is None else ts
    return {
        "X-Odoo-Timestamp": str(stamp),
        "X-Odoo-Signature": f"sha256={sign(secret, stamp, raw)}",
        "Content-Type": "application/json",
    }


class Recorder:
    def __init__(self) -> None:
        self.events: list[OdooEvent] = []

    async def __call__(self, event: OdooEvent) -> None:
        self.events.append(event)


@pytest.fixture
def recorder(env: Env) -> Recorder:
    rec = Recorder()
    bus = env.app.state.container.event_bus
    for event_type in ("partner.created", "partner.updated", "sale_order.confirmed"):
        bus.subscribe(event_type, rec)
    return rec


def post(env: Env, body: dict[str, Any], headers: dict[str, str] | None = None) -> Any:
    raw = encode(body)
    return env.client.post(URL, content=raw, headers=headers or signed_headers(raw))


def test_valid_signature_is_accepted_and_dispatched(env: Env, recorder: Recorder) -> None:
    body = payload()
    response = post(env, body)
    assert response.status_code == 202
    assert response.json() == {"status": "accepted", "event_id": body["event_id"]}
    assert len(recorder.events) == 1
    event = recorder.events[0]
    assert (event.event_type, event.model, event.record_id) == ("partner.created", "res.partner", 7)
    assert event.payload == {"name": "Ada"}
    assert event.occurred_at.tzinfo is not None


def test_bare_hex_signature_is_accepted(env: Env, recorder: Recorder) -> None:
    raw = encode(payload())
    headers = signed_headers(raw)
    headers["X-Odoo-Signature"] = headers["X-Odoo-Signature"].removeprefix("sha256=")
    assert env.client.post(URL, content=raw, headers=headers).status_code == 202
    assert len(recorder.events) == 1


def test_bad_signature_is_401(env: Env, recorder: Recorder) -> None:
    raw = encode(payload())
    headers = signed_headers(raw, secret="another-secret-value-1")
    response = env.client.post(URL, content=raw, headers=headers)
    assert response.status_code == 401
    assert response.json()["error"] == "invalid_signature"
    assert recorder.events == []


@pytest.mark.parametrize("missing", ["X-Odoo-Signature", "X-Odoo-Timestamp"])
def test_missing_headers_are_401(env: Env, recorder: Recorder, missing: str) -> None:
    raw = encode(payload())
    headers = signed_headers(raw)
    del headers[missing]
    response = env.client.post(URL, content=raw, headers=headers)
    assert response.status_code == 401
    assert response.json()["error"] == "invalid_signature"
    assert recorder.events == []


def test_stale_timestamp_is_401_even_with_a_valid_signature(env: Env, recorder: Recorder) -> None:
    raw = encode(payload())
    response = env.client.post(
        URL, content=raw, headers=signed_headers(raw, ts=int(time.time()) - 600)
    )
    assert response.status_code == 401
    assert response.json()["error"] == "invalid_signature"
    assert recorder.events == []


def test_tolerance_is_configurable() -> None:
    gen = build_env(make_settings(webhook_tolerance_seconds=1000))
    env = next(gen)
    try:
        raw = encode(payload())
        headers = signed_headers(raw, ts=int(time.time()) - 600)
        assert env.client.post(URL, content=raw, headers=headers).status_code == 202
    finally:
        gen.close()


def test_tampered_body_is_401(env: Env, recorder: Recorder) -> None:
    raw = encode(payload())
    headers = signed_headers(raw)
    tampered = raw.replace(b'"record_id": 7', b'"record_id": 8')
    assert tampered != raw
    assert env.client.post(URL, content=tampered, headers=headers).status_code == 401
    assert recorder.events == []


def test_duplicate_event_id_is_acknowledged_and_handled_once(env: Env, recorder: Recorder) -> None:
    body = payload()
    first = post(env, body)
    second = post(env, body)
    assert first.status_code == 202
    assert second.status_code == 200
    assert second.json() == {"status": "duplicate", "event_id": body["event_id"]}
    assert len(recorder.events) == 1


def test_a_replayed_signed_request_is_a_duplicate_not_a_second_dispatch(
    env: Env, recorder: Recorder
) -> None:
    raw = encode(payload())
    headers = signed_headers(raw)
    assert env.client.post(URL, content=raw, headers=headers).status_code == 202
    assert env.client.post(URL, content=raw, headers=headers).status_code == 200
    assert len(recorder.events) == 1


def test_a_forged_request_does_not_burn_the_event_id(env: Env, recorder: Recorder) -> None:
    body = payload()
    raw = encode(body)
    bad = signed_headers(raw, secret="another-secret-value-1")
    assert env.client.post(URL, content=raw, headers=bad).status_code == 401
    assert post(env, body).status_code == 202
    assert len(recorder.events) == 1


@pytest.mark.parametrize(
    "overrides",
    [
        {"event_id": "not-a-uuid"},
        {"record_id": 0},
        {"record_id": "x"},
        {"occurred_at": "yesterday"},
        {"payload": "nope"},
        {"model": ""},
    ],
)
def test_invalid_payload_is_422(env: Env, recorder: Recorder, overrides: dict[str, Any]) -> None:
    response = post(env, payload(**overrides))
    assert response.status_code == 422
    assert response.json()["error"] == "validation_error"
    assert recorder.events == []


def test_missing_fields_and_non_json_bodies_are_422(env: Env) -> None:
    assert post(env, {"event_type": "partner.created"}).status_code == 422
    raw = b"not json"
    response = env.client.post(URL, content=raw, headers=signed_headers(raw))
    assert response.status_code == 422


def test_an_invalid_payload_does_not_burn_the_event_id(env: Env, recorder: Recorder) -> None:
    event_id = str(uuid.uuid4())
    assert post(env, payload(event_id=event_id, record_id=0)).status_code == 422
    assert post(env, payload(event_id=event_id)).status_code == 202
    assert len(recorder.events) == 1


def test_unknown_event_type_is_acknowledged_logged_and_ignored(
    env: Env, recorder: Recorder, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.INFO):
        response = post(env, payload(event_type="invoice.paid"))
    assert response.status_code == 202
    assert response.json()["status"] == "ignored"
    assert recorder.events == []
    assert any(r.getMessage() == "ignored unknown event" for r in caplog.records)


def test_oversized_body_is_413(env: Env, recorder: Recorder) -> None:
    raw = encode(payload(payload={"blob": "x" * MAX_BODY}))
    response = env.client.post(URL, content=raw, headers=signed_headers(raw))
    assert response.status_code == 413
    assert response.json()["error"] == "payload_too_large"
    assert recorder.events == []


def test_oversized_chunked_body_without_content_length_is_413(env: Env) -> None:
    def chunks() -> Iterator[bytes]:
        for _ in range(3):
            yield b"x" * (MAX_BODY // 2)

    headers = signed_headers(b"")
    assert env.client.post(URL, content=chunks(), headers=headers).status_code == 413


def test_body_exactly_at_the_limit_is_read(env: Env) -> None:
    raw = b"x" * MAX_BODY
    response = env.client.post(URL, content=raw, headers=signed_headers(raw))
    assert response.status_code == 422  # signed and read in full, but not a valid payload


def test_api_key_is_not_required_even_when_the_connector_key_is_set(
    secured_env: Env,
) -> None:
    raw = encode(payload())
    assert secured_env.client.get("/customers").status_code == 401
    response = secured_env.client.post(URL, content=raw, headers=signed_headers(raw))
    assert response.status_code == 202
    assert "X-API-Key" not in response.request.headers
    assert API_KEY not in response.text


def test_handler_exception_does_not_affect_the_response(env: Env, recorder: Recorder) -> None:
    async def boom(event: OdooEvent) -> None:
        raise RuntimeError("handler bug")

    env.app.state.container.event_bus.subscribe("partner.created", boom)
    response = post(env, payload())
    assert response.status_code == 202
    assert len(recorder.events) == 1


def test_event_store_failure_is_503_so_odoo_retries(env: Env, recorder: Recorder) -> None:
    store = env.app.state.container.webhook_events

    async def broken(*args: object, **kwargs: object) -> str:
        raise RuntimeError("database is locked")

    store.claim = broken
    response = post(env, payload())
    assert response.status_code == 503
    assert response.json()["error"] == "webhook_store_unavailable"
    assert recorder.events == []


def test_all_known_event_types_are_dispatched(env: Env, recorder: Recorder) -> None:
    post(env, payload(event_type="partner.updated"))
    post(env, payload(event_type="sale_order.confirmed", model="sale.order", record_id=3))
    assert [e.event_type for e in recorder.events] == ["partner.updated", "sale_order.confirmed"]


def test_a_naive_timestamp_is_interpreted_as_utc(env: Env, recorder: Recorder) -> None:
    post(env, payload(occurred_at="2026-01-02T03:04:05"))
    assert recorder.events[0].occurred_at == datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC)


def test_default_handlers_are_registered_at_startup(env: Env) -> None:
    bus = env.app.state.container.event_bus
    assert bus._handlers["partner.created"]
    assert bus._handlers["sale_order.confirmed"]


# --- at-least-once delivery: received -> processed -------------------------------------------


def _store(env: Env) -> Any:
    return env.app.state.container.webhook_events


def _status(env: Env, event_id: str) -> str | None:
    import asyncio

    return asyncio.run(_store(env).status(event_id))


def test_a_successfully_handled_event_is_marked_processed(env: Env, recorder: Recorder) -> None:
    body = payload()
    assert post(env, body).status_code == 202
    assert _status(env, body["event_id"]) == "processed"


def test_a_failing_handler_leaves_the_event_received(env: Env) -> None:
    async def boom(event: OdooEvent) -> None:
        raise RuntimeError("handler bug")

    env.app.state.container.event_bus.subscribe("partner.created", boom)
    body = payload()
    assert post(env, body).status_code == 202
    assert _status(env, body["event_id"]) == "received"


def test_a_received_event_is_redispatched_once_the_redelivery_window_passed(env: Env) -> None:
    calls: list[int] = []
    fail = {"on": True}

    async def flaky(event: OdooEvent) -> None:
        calls.append(event.record_id)
        if fail["on"]:
            raise RuntimeError("temporary outage")

    env.app.state.container.event_bus.subscribe("partner.created", flaky)
    body = payload()
    assert post(env, body).status_code == 202
    assert _status(env, body["event_id"]) == "received"

    # within the window the delivery counts as in flight: acknowledged, not dispatched again
    inflight = post(env, body)
    assert inflight.status_code == 200
    assert inflight.json() == {"status": "duplicate", "event_id": body["event_id"]}
    assert len(calls) == 1

    # Odoo redelivers after the window and the handler recovered: dispatched again, now processed
    fail["on"] = False
    _store(env).clock = lambda: datetime.now(UTC) + timedelta(seconds=61)
    retry = post(env, body)
    assert retry.status_code == 202
    assert retry.json() == {"status": "accepted", "event_id": body["event_id"]}
    assert len(calls) == 2
    assert _status(env, body["event_id"]) == "processed"

    again = post(env, body)
    assert again.status_code == 200
    assert len(calls) == 2


def test_a_processed_event_is_never_redispatched(env: Env, recorder: Recorder) -> None:
    body = payload()
    assert post(env, body).status_code == 202
    _store(env).clock = lambda: datetime.now(UTC) + timedelta(days=1)
    assert post(env, body).status_code == 200
    assert len(recorder.events) == 1


def test_redelivery_window_is_configurable() -> None:
    gen = build_env(make_settings(webhook_redelivery_after_seconds=5))
    env = next(gen)
    try:
        failing = {"on": True}
        calls: list[int] = []

        async def flaky(event: OdooEvent) -> None:
            calls.append(1)
            if failing["on"]:
                raise RuntimeError("x")

        env.app.state.container.event_bus.subscribe("partner.created", flaky)
        body = payload()
        post(env, body)
        failing["on"] = False
        _store(env).clock = lambda: datetime.now(UTC) + timedelta(seconds=6)
        assert post(env, body).status_code == 202
        assert len(calls) == 2
    finally:
        gen.close()


def test_marking_processed_failing_is_logged_and_the_response_is_unaffected(
    env: Env, recorder: Recorder, caplog: pytest.LogCaptureFixture
) -> None:
    async def broken(*args: object, **kwargs: object) -> None:
        raise RuntimeError("database is locked")

    _store(env).mark_processed = broken
    body = payload()
    with caplog.at_level(logging.ERROR):
        assert post(env, body).status_code == 202
    assert any("could not mark" in r.getMessage() for r in caplog.records)
    assert len(recorder.events) == 1
