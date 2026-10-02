import hashlib
import hmac

import pytest

from conector_odoo.infrastructure.webhooks.signature import sign, verify

SECRET = "whsec-test-secret-123"
BODY = b'{"event_id":"e","record_id":1}'
NOW = 1_700_000_000


def reference(timestamp: int, body: bytes) -> str:
    message = f"{timestamp}.".encode() + body
    return hmac.new(SECRET.encode(), message, hashlib.sha256).hexdigest()


def test_sign_is_hmac_sha256_over_timestamp_dot_body_as_lowercase_hex() -> None:
    assert sign(SECRET, NOW, BODY) == reference(NOW, BODY)
    assert sign(SECRET, str(NOW), BODY) == reference(NOW, BODY)


def test_verify_accepts_prefixed_and_bare_signatures() -> None:
    digest = sign(SECRET, NOW, BODY)
    assert verify(SECRET, str(NOW), BODY, f"sha256={digest}", NOW, 300)
    assert verify(SECRET, str(NOW), BODY, digest, NOW, 300)
    assert verify(SECRET, str(NOW), BODY, digest.upper(), NOW, 300)


def test_verify_rejects_a_tampered_body_secret_or_timestamp() -> None:
    digest = sign(SECRET, NOW, BODY)
    assert not verify(SECRET, str(NOW), BODY + b" ", digest, NOW, 300)
    assert not verify("another-secret-value-1", str(NOW), BODY, digest, NOW, 300)
    assert not verify(SECRET, str(NOW + 1), BODY, digest, NOW, 300)


@pytest.mark.parametrize("offset", [301, -301, 10_000])
def test_verify_rejects_timestamps_outside_the_tolerance(offset: int) -> None:
    ts = NOW + offset
    assert not verify(SECRET, str(ts), BODY, sign(SECRET, ts, BODY), NOW, 300)


@pytest.mark.parametrize("offset", [300, -300, 0])
def test_verify_accepts_timestamps_on_the_tolerance_boundary(offset: int) -> None:
    ts = NOW + offset
    assert verify(SECRET, str(ts), BODY, sign(SECRET, ts, BODY), NOW, 300)


@pytest.mark.parametrize(
    "timestamp", ["", "abc", "12.5", "-5", " 1700000000", "\uff11\uff17\uff10\uff10"]
)
def test_verify_rejects_malformed_timestamps(timestamp: str) -> None:
    assert not verify(SECRET, timestamp, BODY, sign(SECRET, NOW, BODY), NOW, 300)


@pytest.mark.parametrize("signature", ["", "sha256=", "sha1=abcd", "zz", "sha256=é", "é"])
def test_verify_rejects_malformed_signatures_without_raising(signature: str) -> None:
    assert not verify(SECRET, str(NOW), BODY, signature, NOW, 300)
