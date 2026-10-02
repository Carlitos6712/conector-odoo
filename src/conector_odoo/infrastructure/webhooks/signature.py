"""Webhook signing scheme shared by the connector and the Odoo addon.

Scheme (the addon must produce exactly this)::

    message   = f"{timestamp}.".encode("utf-8") + raw_request_body
    signature = HMAC-SHA256(key=webhook_secret.encode("utf-8"), msg=message).hexdigest()
                # lowercase hex

``timestamp`` is the Unix time in whole seconds, sent as ASCII digits in ``X-Odoo-Timestamp``; the
signature travels in ``X-Odoo-Signature`` as ``sha256=<hex>`` (bare ``<hex>`` is also accepted).
Binding the timestamp into the MAC lets the receiver reject replays older than a tolerance window.
"""

import hashlib
import hmac

SIGNATURE_PREFIX = "sha256="
# Unix seconds have 10 digits until the year 2286; 12 leaves headroom and bounds ``int()`` work.
MAX_TIMESTAMP_DIGITS = 12


def sign(secret: str, timestamp: int | str, body: bytes) -> str:
    """Return the lowercase hex HMAC-SHA256 of ``"<timestamp>." + body``."""
    message = f"{timestamp}.".encode() + body
    return hmac.new(secret.encode(), message, hashlib.sha256).hexdigest()


def verify(
    secret: str,
    timestamp: str,
    body: bytes,
    signature: str,
    now: float,
    tolerance: float,
) -> bool:
    """Check freshness (``|now - timestamp| <= tolerance``) and the signature in constant time.

    Never raises on malformed input: anything unparseable is simply invalid.
    """
    if not (timestamp.isascii() and timestamp.isdigit()) or len(timestamp) > MAX_TIMESTAMP_DIGITS:
        return False
    if abs(now - int(timestamp)) > tolerance:
        return False
    candidate = signature.removeprefix(SIGNATURE_PREFIX).lower()
    if not candidate.isascii():
        return False
    expected = sign(secret, timestamp, body)
    return hmac.compare_digest(candidate.encode(), expected.encode())
