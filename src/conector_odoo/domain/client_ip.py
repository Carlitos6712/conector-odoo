"""Client address resolution and normalisation for login throttling (pure, stdlib only)."""

import ipaddress
from collections.abc import Sequence

UNKNOWN_IP = "unknown"
_MAX_KEY_LENGTH = 64


def resolve_client_ip(peer: str | None, forwarded_for: Sequence[str], trusted_proxies: int) -> str:
    """The address to throttle: the socket peer, or the proxy-reported client address.

    ``forwarded_for`` holds the raw ``X-Forwarded-For`` header lines. It is honoured ONLY when
    ``trusted_proxies`` > 0, and then by counting from the RIGHT: each of the N trusted proxies
    appended the address it received the request from, so the client is the N-th entry from the
    right. Anything to its left is client-supplied and never trusted. When the chain is shorter than
    N or the chosen entry is not an IP address, the header cannot be trusted and the peer is used.
    """
    if not peer:
        return UNKNOWN_IP
    if trusted_proxies <= 0:
        return peer
    entries = [part.strip() for line in forwarded_for for part in line.split(",")]
    if len(entries) < trusted_proxies:
        return peer
    candidate = entries[-trusted_proxies]
    try:
        ipaddress.ip_address(candidate)
    except ValueError:
        return peer
    return candidate


def client_ip_key(address: str) -> str:
    """Normalise an address into a throttle key: IPv4-mapped IPv6 becomes IPv4 and IPv6 is grouped
    by /64 (a single host owns a whole /64, so per-address keys would be trivially evaded)."""
    try:
        ip = ipaddress.ip_address(address.strip())
    except ValueError:
        return address.strip().lower()[:_MAX_KEY_LENGTH] or UNKNOWN_IP
    if isinstance(ip, ipaddress.IPv6Address):
        if ip.ipv4_mapped is not None:
            return str(ip.ipv4_mapped)
        return str(ipaddress.ip_network((ip, 64), strict=False))
    return str(ip)
