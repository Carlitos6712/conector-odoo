"""Outbound URL policy (SSRF defence): which destinations the connector may contact.

Pure rules over ``ipaddress``; resolving names and enforcing the verdict at connect time is the
infrastructure's job (``infrastructure/net``).

* Always blocked, in every mode and even for allow-listed hosts: link-local (169.254.0.0/16,
  fe80::/10, which covers the cloud metadata address 169.254.169.254), the IPv6 metadata address
  fd00:ec2::254, Alibaba's 100.100.100.200, unspecified and "this network" (0.0.0.0/8, ::),
  multicast and reserved/broadcast ranges. IPv4 addresses embedded in IPv4-mapped, NAT64 and 6to4
  IPv6 addresses are checked as IPv4. Only http and https are allowed.
* ``default`` mode allows everything else: Odoo and target APIs are usually internal.
* ``strict`` mode additionally blocks every non-global address (RFC 1918, loopback, ULA, CGNAT)
  unless the host is listed in the allow list.
"""

import ipaddress
from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum
from urllib.parse import urlsplit

from conector_odoo.domain.errors import OutboundUrlBlocked

IPAddress = ipaddress.IPv4Address | ipaddress.IPv6Address

_METADATA = frozenset(
    {
        ipaddress.ip_address("169.254.169.254"),
        ipaddress.ip_address("fd00:ec2::254"),
        ipaddress.ip_address("100.100.100.200"),
    }
)
_THIS_NETWORK = ipaddress.ip_network("0.0.0.0/8")
_NAT64 = ipaddress.ip_network("64:ff9b::/96")
_SIX_TO_FOUR = ipaddress.ip_network("2002::/16")


class OutboundMode(StrEnum):
    DEFAULT = "default"
    STRICT = "strict"


def _embedded_ipv4(ip: ipaddress.IPv6Address) -> ipaddress.IPv4Address | None:
    if ip.ipv4_mapped is not None:
        return ip.ipv4_mapped
    if ip in _NAT64:
        return ipaddress.IPv4Address(int(ip) & 0xFFFFFFFF)
    if ip in _SIX_TO_FOUR:
        return ipaddress.IPv4Address((int(ip) >> 80) & 0xFFFFFFFF)
    return None


def _always_blocked(ip: IPAddress) -> str | None:
    if isinstance(ip, ipaddress.IPv6Address):
        embedded = _embedded_ipv4(ip)
        if embedded is not None:
            return _always_blocked(embedded)
    if ip in _METADATA or ip.is_link_local:
        return "link-local or cloud metadata address"
    if ip.is_unspecified or (isinstance(ip, ipaddress.IPv4Address) and ip in _THIS_NETWORK):
        return "unspecified address"
    if ip.is_multicast:
        return "multicast address"
    # IPv4 240.0.0.0/4 (incl. broadcast). Not for IPv6: Python's list there contains ::/8, i.e. ::1.
    if isinstance(ip, ipaddress.IPv4Address) and ip.is_reserved:
        return "reserved address"
    return None


def _effective(ip: IPAddress) -> IPAddress:
    if isinstance(ip, ipaddress.IPv6Address):
        return _embedded_ipv4(ip) or ip
    return ip


def _parse(value: str) -> IPAddress | None:
    try:
        return ipaddress.ip_address(value.strip().strip("[]"))
    except ValueError:
        return None


@dataclass(frozen=True, slots=True)
class OutboundPolicy:
    mode: OutboundMode = OutboundMode.DEFAULT
    allowed_hosts: frozenset[str] = frozenset()  # lower-case names or IP literals (strict mode)

    @classmethod
    def from_values(cls, mode: str, allowed_hosts: str) -> "OutboundPolicy":
        """Build from the raw settings values (``allowed_hosts`` is a comma-separated list)."""
        hosts = frozenset(h.strip().lower() for h in allowed_hosts.split(",") if h.strip())
        return cls(OutboundMode(mode), hosts)

    def check_url(self, url: str) -> None:
        """Scheme and literal-IP checks that need no DNS. Raises ``OutboundUrlBlocked``."""
        try:
            parts = urlsplit(url.strip())
            host = parts.hostname
        except ValueError:
            raise OutboundUrlBlocked(
                "outbound request blocked by the URL policy: the URL is malformed"
            ) from None
        if parts.scheme.lower() not in ("http", "https") or not host:
            raise OutboundUrlBlocked(
                "outbound request blocked by the URL policy: only http and https URLs with a "
                "host are allowed"
            )
        literal = _parse(host)
        if literal is not None:
            self.check_addresses(host, [str(literal)])

    def check_addresses(self, host: str, addresses: Sequence[str]) -> None:
        """Every address ``host`` resolved to must pass; one bad address blocks the whole answer
        (otherwise a name with a public and a metadata record could be connected either way)."""
        if not addresses:
            raise OutboundUrlBlocked(
                "outbound request blocked by the URL policy: the host did not resolve"
            )
        allowed = host.strip().strip("[]").lower() in self.allowed_hosts
        for raw in addresses:
            ip = _parse(raw)
            if ip is None:
                raise OutboundUrlBlocked(
                    "outbound request blocked by the URL policy: unrecognised address"
                )
            reason = _always_blocked(ip)
            strict_block = (
                self.mode is OutboundMode.STRICT and not allowed and not _effective(ip).is_global
            )
            if reason is None and strict_block:
                reason = (
                    "private or loopback address (strict policy: list the host in "
                    "OUTBOUND_ALLOWED_HOSTS to allow it)"
                )
            if reason is not None:
                raise OutboundUrlBlocked(
                    f"outbound request blocked by the URL policy: the host resolves to a {reason}"
                )


DEFAULT_POLICY = OutboundPolicy()
