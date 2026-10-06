import pytest

from conector_odoo.domain.errors import OutboundUrlBlocked, RemoteUnavailable
from conector_odoo.domain.outbound import DEFAULT_POLICY, OutboundMode, OutboundPolicy

STRICT = OutboundPolicy(OutboundMode.STRICT)
ALWAYS_BLOCKED = [
    "169.254.169.254",  # cloud metadata
    "169.254.0.1",
    "fe80::1",
    "fd00:ec2::254",  # AWS IMDS over IPv6
    "0.0.0.0",
    "0.1.2.3",
    "::",
    "224.0.0.1",
    "ff02::1",
    "255.255.255.255",
    "100.100.100.200",  # Alibaba metadata
    "::ffff:169.254.169.254",  # IPv4-mapped IPv6 must not smuggle a blocked address
    "64:ff9b::a9fe:a9fe",  # NAT64 embedding 169.254.169.254
    "2002:a9fe:a9fe::1",  # 6to4 embedding 169.254.169.254
]
PRIVATE = [
    "10.1.2.3",
    "172.16.0.9",
    "192.168.1.1",
    "127.0.0.1",
    "::1",
    "fd12:3456::1",
    "100.64.0.1",
]
PUBLIC = ["93.184.216.34", "2606:4700:4700::1111"]


def test_blocked_error_is_a_remote_unavailable_without_leaking_the_host() -> None:
    with pytest.raises(OutboundUrlBlocked) as excinfo:
        DEFAULT_POLICY.check_addresses("secret-host.internal", ["169.254.169.254"])
    assert isinstance(excinfo.value, RemoteUnavailable)
    assert "secret-host" not in str(excinfo.value) and "169.254" not in str(excinfo.value)


@pytest.mark.parametrize("address", ALWAYS_BLOCKED)
@pytest.mark.parametrize("policy", [DEFAULT_POLICY, STRICT])
def test_always_blocked_classes(address: str, policy: OutboundPolicy) -> None:
    with pytest.raises(OutboundUrlBlocked):
        policy.check_addresses("example.com", [address])


@pytest.mark.parametrize("address", ALWAYS_BLOCKED)
def test_the_allowlist_never_unblocks_an_always_blocked_class(address: str) -> None:
    policy = OutboundPolicy(OutboundMode.STRICT, frozenset({"example.com"}))
    with pytest.raises(OutboundUrlBlocked):
        policy.check_addresses("example.com", [address])


@pytest.mark.parametrize("address", PRIVATE + PUBLIC)
def test_default_mode_allows_private_loopback_and_public(address: str) -> None:
    DEFAULT_POLICY.check_addresses("example.com", [address])


@pytest.mark.parametrize("address", PUBLIC)
def test_strict_mode_allows_public_addresses(address: str) -> None:
    STRICT.check_addresses("example.com", [address])


@pytest.mark.parametrize("address", PRIVATE)
def test_strict_mode_blocks_private_and_loopback(address: str) -> None:
    with pytest.raises(OutboundUrlBlocked):
        STRICT.check_addresses("example.com", [address])


@pytest.mark.parametrize("address", PRIVATE)
def test_strict_mode_allowlist_admits_private_hosts_case_insensitively(address: str) -> None:
    policy = OutboundPolicy(OutboundMode.STRICT, frozenset({"odoo.internal", address}))
    policy.check_addresses("ODOO.internal", [address])
    policy.check_addresses(address, [address])


def test_strict_allowlist_is_per_host_not_global() -> None:
    policy = OutboundPolicy(OutboundMode.STRICT, frozenset({"odoo.internal"}))
    with pytest.raises(OutboundUrlBlocked):
        policy.check_addresses("other.internal", ["10.0.0.5"])


def test_one_bad_address_blocks_a_mixed_answer() -> None:
    with pytest.raises(OutboundUrlBlocked):
        DEFAULT_POLICY.check_addresses("example.com", ["93.184.216.34", "169.254.169.254"])
    with pytest.raises(OutboundUrlBlocked):
        DEFAULT_POLICY.check_addresses("example.com", ["169.254.169.254", "93.184.216.34"])


def test_an_empty_answer_is_blocked() -> None:
    with pytest.raises(OutboundUrlBlocked):
        DEFAULT_POLICY.check_addresses("example.com", [])


def test_unparseable_address_is_blocked() -> None:
    with pytest.raises(OutboundUrlBlocked):
        DEFAULT_POLICY.check_addresses("example.com", ["not-an-ip"])


@pytest.mark.parametrize(
    "url", ["ftp://example.com/x", "file:///etc/passwd", "gopher://example.com", "//example.com"]
)
def test_non_http_schemes_are_refused(url: str) -> None:
    with pytest.raises(OutboundUrlBlocked):
        DEFAULT_POLICY.check_url(url)


def test_url_without_host_is_refused() -> None:
    with pytest.raises(OutboundUrlBlocked):
        DEFAULT_POLICY.check_url("http:///path")


@pytest.mark.parametrize(
    "url",
    [
        "http://169.254.169.254/latest/meta-data",
        "https://[fd00:ec2::254]/",
        "http://0.0.0.0:8000",
        "http://[::ffff:169.254.169.254]/",
    ],
)
def test_literal_blocked_hosts_fail_before_any_dns(url: str) -> None:
    with pytest.raises(OutboundUrlBlocked):
        DEFAULT_POLICY.check_url(url)


def test_url_check_accepts_names_and_private_literals_in_default_mode() -> None:
    for url in ("https://api.example.com/x", "http://localhost:8000", "http://10.0.0.5/odoo"):
        DEFAULT_POLICY.check_url(url)


def test_strict_url_check_refuses_a_private_literal_unless_allowed() -> None:
    with pytest.raises(OutboundUrlBlocked):
        STRICT.check_url("http://10.0.0.5/odoo")
    OutboundPolicy(OutboundMode.STRICT, frozenset({"10.0.0.5"})).check_url("http://10.0.0.5/odoo")


def test_policy_from_settings_values_parses_the_comma_list() -> None:
    policy = OutboundPolicy.from_values("strict", " Odoo.Internal , ,10.0.0.5")
    assert policy.mode is OutboundMode.STRICT
    assert policy.allowed_hosts == frozenset({"odoo.internal", "10.0.0.5"})
