import pytest

from conector_odoo.domain.client_ip import UNKNOWN_IP, client_ip_key, resolve_client_ip


def test_zero_trusted_proxies_ignores_the_header_entirely() -> None:
    assert resolve_client_ip("10.0.0.5", ["1.2.3.4"], 0) == "10.0.0.5"


def test_missing_peer_is_unknown() -> None:
    assert resolve_client_ip(None, [], 0) == UNKNOWN_IP
    assert resolve_client_ip("", ["1.2.3.4"], 1) == UNKNOWN_IP


def test_one_proxy_takes_the_right_most_entry_never_the_left_most() -> None:
    # The proxy appended the real client (203.0.113.9); the left value is attacker-controlled.
    assert resolve_client_ip("10.0.0.1", ["6.6.6.6, 203.0.113.9"], 1) == "203.0.113.9"


def test_two_proxies_take_the_second_from_the_right() -> None:
    chain = ["6.6.6.6, 203.0.113.9, 10.0.0.2"]
    assert resolve_client_ip("10.0.0.1", chain, 2) == "203.0.113.9"


def test_multiple_header_lines_are_joined_in_order() -> None:
    assert resolve_client_ip("10.0.0.1", ["6.6.6.6", "203.0.113.9"], 1) == "203.0.113.9"


def test_short_chain_falls_back_to_the_peer() -> None:
    # Fewer entries than trusted proxies: the header cannot be trusted, use the socket peer.
    assert resolve_client_ip("10.0.0.1", [], 1) == "10.0.0.1"
    assert resolve_client_ip("10.0.0.1", ["1.2.3.4"], 2) == "10.0.0.1"


def test_garbage_entry_falls_back_to_the_peer() -> None:
    assert resolve_client_ip("10.0.0.1", ["1.2.3.4, not-an-ip"], 1) == "10.0.0.1"
    assert resolve_client_ip("10.0.0.1", ["1.2.3.4, "], 1) == "10.0.0.1"


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("203.0.113.9", "203.0.113.9"),
        ("::ffff:203.0.113.9", "203.0.113.9"),
        ("2001:db8:abcd:12:1:2:3:4", "2001:db8:abcd:12::/64"),
        ("2001:db8:abcd:12:ffff::1", "2001:db8:abcd:12::/64"),
        ("UNKNOWN", "unknown"),
        ("testclient", "testclient"),
    ],
)
def test_key_normalises_mapped_ipv4_and_groups_ipv6_by_64(raw: str, expected: str) -> None:
    assert client_ip_key(raw) == expected


def test_key_is_bounded() -> None:
    assert len(client_ip_key("x" * 500)) <= 64
