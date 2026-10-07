import ipaddress
import socket

import pytest

from tools.url_safety import UnsafeURL, validate_url

PUBLIC = "93.184.216.34"


@pytest.fixture(autouse=True)
def fake_dns(monkeypatch):
    """No real DNS in tests. IP literals resolve to themselves; names use the table."""
    table = {
        "example.com": [PUBLIC],
        "evil.example": ["127.0.0.1"],
        "mixed.example": [PUBLIC, "10.0.0.5"],
    }

    def fake(host, port, *args, **kwargs):
        try:
            ipaddress.ip_address(host)
            addrs = [host]
        except ValueError:
            if host not in table:
                raise socket.gaierror("no such host")
            addrs = table[host]
        return [
            (socket.AF_INET6 if ":" in a else socket.AF_INET, socket.SOCK_STREAM, 6, "", (a, port))
            for a in addrs
        ]

    monkeypatch.setattr(socket, "getaddrinfo", fake)


def test_public_https_url_is_allowed():
    assert validate_url("https://example.com/path?q=1") == "https://example.com/path?q=1"


def test_scheme_is_case_insensitive_and_whitespace_trimmed():
    assert validate_url("  HTTP://example.com  ") == "HTTP://example.com"


def test_public_ip_literal_is_allowed():
    assert validate_url(f"http://{PUBLIC}/")


@pytest.mark.parametrize("url", [
    "file:///etc/passwd",
    "ftp://example.com/x",
    "gopher://example.com/",
    "javascript:alert(1)",
    "example.com/no-scheme",
])
def test_bad_schemes_are_blocked(url):
    with pytest.raises(UnsafeURL):
        validate_url(url)


def test_credentials_are_blocked():
    with pytest.raises(UnsafeURL):
        validate_url("http://user:pw@example.com/")


@pytest.mark.parametrize("url", [
    "http://example.com:22/",
    "http://example.com:6379/",
    "https://example.com:8443/",
])
def test_odd_ports_are_blocked(url):
    with pytest.raises(UnsafeURL):
        validate_url(url)


@pytest.mark.parametrize("url", [
    "http://127.0.0.1/",
    "http://10.0.0.5/",
    "http://192.168.1.1/",
    "http://172.16.0.1/",
    "http://169.254.169.254/latest/meta-data/",  # cloud metadata
    "http://0.0.0.0/",
    "http://100.64.0.1/",                         # carrier-grade NAT
    "http://[::1]/",
    "http://[fd00::1]/",
    "http://[::ffff:127.0.0.1]/",                 # IPv4-mapped IPv6
])
def test_internal_addresses_are_blocked(url):
    with pytest.raises(UnsafeURL):
        validate_url(url)


def test_name_that_resolves_to_private_ip_is_blocked():
    with pytest.raises(UnsafeURL):
        validate_url("http://evil.example/")


def test_one_private_address_among_public_ones_blocks_the_url():
    with pytest.raises(UnsafeURL):
        validate_url("http://mixed.example/")


def test_unresolvable_host_is_blocked():
    with pytest.raises(UnsafeURL):
        validate_url("http://does-not-exist.example/")


@pytest.mark.parametrize("url", ["", "   ", None, "http://", "http://example.com/\r\nHost: x"])
def test_empty_or_malformed_is_blocked(url):
    with pytest.raises(UnsafeURL):
        validate_url(url)


def test_overlong_url_is_blocked():
    with pytest.raises(UnsafeURL):
        validate_url("http://example.com/" + "a" * 3000)