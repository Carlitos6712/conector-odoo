import io
import json
import logging

import pytest

from conector_odoo.logging import configure_logging, redact


def _capture(level: str = "INFO") -> io.StringIO:
    stream = io.StringIO()
    configure_logging(level, stream=stream)
    return stream


@pytest.fixture(autouse=True)
def _restore_root() -> object:
    root = logging.getLogger()
    handlers, level = list(root.handlers), root.level
    yield
    root.handlers[:] = handlers
    root.setLevel(level)


def test_redact_masks_sensitive_keys_recursively() -> None:
    data = {
        "api_key": "abc",
        "Authorization": "Bearer x",
        "nested": {"password": "p", "ok": 1, "items": [{"X-Odoo-Signature": "sig"}]},
        "client_secret": "s",
    }
    result = redact(data)
    assert result["api_key"] == "***"
    assert result["Authorization"] == "***"
    assert result["nested"]["password"] == "***"
    assert result["nested"]["ok"] == 1
    assert result["nested"]["items"][0]["X-Odoo-Signature"] == "***"
    assert result["client_secret"] == "***"
    assert data["api_key"] == "abc"  # input untouched


def test_logs_are_json_with_extras() -> None:
    stream = _capture()
    logging.getLogger("conector_odoo.test").info("hello", extra={"record_id": 7})
    payload = json.loads(stream.getvalue().strip())
    assert payload["message"] == "hello"
    assert payload["level"] == "INFO"
    assert payload["logger"] == "conector_odoo.test"
    assert payload["record_id"] == 7
    assert "timestamp" in payload


def test_extras_with_secrets_are_masked() -> None:
    stream = _capture()
    logging.getLogger("conector_odoo.test").info(
        "call", extra={"api_key": "topsecret", "params": {"password": "pw", "n": 1}}
    )
    raw = stream.getvalue()
    assert "topsecret" not in raw
    assert "pw" not in json.loads(raw)["params"]["password"]
    assert json.loads(raw)["params"]["n"] == 1


def test_level_is_respected() -> None:
    stream = _capture("WARNING")
    logging.getLogger("conector_odoo.test").info("quiet")
    assert stream.getvalue() == ""


def test_exceptions_are_serialized() -> None:
    stream = _capture()
    try:
        raise ValueError("boom")
    except ValueError:
        logging.getLogger("conector_odoo.test").exception("failed")
    payload = json.loads(stream.getvalue().strip())
    assert "ValueError: boom" in payload["exception"]
