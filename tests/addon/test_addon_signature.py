"""The Odoo addon's pure helpers (no ``odoo`` import) must match what the connector verifies."""

import ast
import importlib.util
import json
import logging
import time
import uuid
import xml.etree.ElementTree as ET
from datetime import datetime
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

from conector_odoo.infrastructure.webhooks.signature import verify

ADDON = Path(__file__).resolve().parents[2] / "odoo_addon" / "connector_webhook"
SECRET = "whsec-test-secret-123"
URL = "https://connector.test/webhooks/odoo"


def load_signing() -> ModuleType:
    spec = importlib.util.spec_from_file_location("addon_signing", ADDON / "models" / "signing.py")
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


signing = load_signing()


def test_sign_output_verifies_with_the_connector() -> None:
    body = signing.serialize_body({"event_id": "e", "payload": {"name": "Zoë"}})
    now = int(time.time())
    digest = signing.sign(SECRET, now, body)
    assert digest == digest.lower()
    assert verify(SECRET, str(now), body, f"sha256={digest}", now, 300)
    assert not verify("another-secret-value-1", str(now), body, f"sha256={digest}", now, 300)


def test_headers_follow_the_connector_contract() -> None:
    body = b'{"a":1}'
    headers = signing.build_headers(SECRET, 1_700_000_000, body)
    assert headers["Content-Type"] == "application/json"
    assert headers["X-Odoo-Timestamp"] == "1700000000"
    assert headers["X-Odoo-Signature"].startswith("sha256=")
    assert verify(
        SECRET, headers["X-Odoo-Timestamp"], body, headers["X-Odoo-Signature"], 1_700_000_000, 300
    )


def test_body_is_compact_utf8_json() -> None:
    body = signing.serialize_body({"a": 1, "b": ["é"]})
    assert body == b'{"a":1,"b":["\\u00e9"]}'  # json.dumps default: ASCII-escaped, no spaces


def test_build_event_has_the_shape_the_connector_expects() -> None:
    event = signing.build_event("partner.created", "res.partner", 7, {"name": "Ada"})
    assert set(event) == {"event_id", "event_type", "model", "record_id", "occurred_at", "payload"}
    uuid.UUID(event["event_id"])
    assert (event["event_type"], event["model"], event["record_id"]) == (
        "partner.created",
        "res.partner",
        7,
    )
    assert datetime.fromisoformat(event["occurred_at"]).utcoffset().total_seconds() == 0
    assert event["payload"] == {"name": "Ada"}


class FakeResponse:
    def __init__(self, status_code: int) -> None:
        self.status_code = status_code


class FakePost:
    """Records each call and replays a script of status codes or exceptions."""

    def __init__(self, *script: int | Exception) -> None:
        self.script = list(script)
        self.calls: list[dict[str, Any]] = []

    def __call__(self, url: str, **kwargs: Any) -> FakeResponse:
        self.calls.append({"url": url, **kwargs})
        step = self.script.pop(0)
        if isinstance(step, Exception):
            raise step
        return FakeResponse(step)


def deliver(post: FakePost, clock: list[int] | None = None, **kwargs: Any) -> Any:
    ticks = iter(clock or range(1_700_000_000, 1_700_000_100))
    sleeps: list[float] = []
    result = signing.deliver(
        post,
        URL,
        SECRET,
        signing.serialize_body({"event_id": "fixed", "n": 1}),
        sleep=sleeps.append,
        now=lambda: next(ticks),
        **kwargs,
    )
    return result, sleeps


@pytest.mark.parametrize("status", [200, 202])
def test_success_is_not_retried(status: int) -> None:
    post = FakePost(status)
    result, sleeps = deliver(post)
    assert result.ok is True
    assert (result.attempts, result.status_code) == (1, status)
    assert sleeps == []
    assert post.calls[0]["url"] == URL
    assert post.calls[0]["timeout"] == 5.0


@pytest.mark.parametrize("status", [400, 401, 404, 413, 422])
def test_client_errors_are_never_retried(status: int) -> None:
    post = FakePost(status)
    result, _ = deliver(post)
    assert result.ok is False
    assert (result.attempts, result.status_code) == (1, status)


def test_5xx_and_connection_errors_are_retried_with_fresh_timestamp_and_same_event() -> None:
    post = FakePost(503, ConnectionError("down"), 502, 202)
    result, sleeps = deliver(post)
    assert result.ok is True
    assert result.attempts == 4
    assert len(sleeps) == 3
    assert sleeps == sorted(sleeps)  # backoff grows
    bodies = {call["data"] for call in post.calls}
    assert len(bodies) == 1  # same bytes, hence the same event_id
    stamps = [call["headers"]["X-Odoo-Timestamp"] for call in post.calls]
    assert len(set(stamps)) == 4  # a fresh timestamp for every attempt
    for call in post.calls:
        headers = call["headers"]
        assert verify(
            SECRET,
            headers["X-Odoo-Timestamp"],
            call["data"],
            headers["X-Odoo-Signature"],
            int(headers["X-Odoo-Timestamp"]),
            300,
        )


def test_gives_up_after_three_retries() -> None:
    post = FakePost(500, 500, 500, 500, 500)
    result, sleeps = deliver(post)
    assert result.ok is False
    assert result.attempts == 4  # first attempt + 3 retries
    assert len(sleeps) == 3
    assert len(post.script) == 1


def test_a_non_retryable_status_after_a_retry_stops_immediately() -> None:
    post = FakePost(503, 401, 202)
    result, _ = deliver(post)
    assert (result.ok, result.attempts, result.status_code) == (False, 2, 401)


def test_the_secret_is_never_logged(caplog: pytest.LogCaptureFixture) -> None:
    post = FakePost(ConnectionError(f"boom {SECRET}"), 500, 500, 500)
    with caplog.at_level(logging.DEBUG):
        deliver(post)
    assert caplog.records
    assert SECRET not in caplog.text


def test_manifest_parses_and_declares_the_dependencies() -> None:
    manifest = ast.literal_eval((ADDON / "__manifest__.py").read_text(encoding="utf-8"))
    assert manifest["name"] == "FastAPI Connector Webhooks"
    assert manifest["version"] == "17.0.1.0.0"
    assert manifest["depends"] == ["base", "sale", "base_automation"]
    assert manifest["license"] == "LGPL-3"
    assert manifest["installable"] is True
    for relative in manifest["data"]:
        assert (ADDON / relative).is_file(), relative


@pytest.mark.parametrize("path", sorted((ADDON / "data").glob("*.xml")) if ADDON.exists() else [])
def test_xml_data_files_are_well_formed(path: Path) -> None:
    root = ET.parse(path).getroot()
    assert root.tag == "odoo"


def test_automations_cover_the_three_events() -> None:
    root = ET.parse(ADDON / "data" / "base_automation.xml").getroot()
    text = ET.tostring(root, encoding="unicode")
    for event in ("partner.created", "partner.updated", "sale_order.confirmed"):
        assert f"'{event}'" in text
    # the server action snippet must be valid Python
    for node in root.iter("field"):
        if node.get("name") == "code" and node.text:
            ast.parse(node.text.strip())


def test_config_parameter_data_has_no_secret() -> None:
    root = ET.parse(ADDON / "data" / "ir_config_parameter.xml").getroot()
    keys = {n.text for n in root.iter("field") if n.get("name") == "key"}
    assert "connector_webhook.url" in keys
    assert "connector_webhook.secret" not in keys
    assert root.find("data").get("noupdate") == "1"  # type: ignore[union-attr]


def test_json_dumps_separators_match_the_wire_format() -> None:
    assert json.loads(signing.serialize_body({"k": "v"})) == {"k": "v"}
