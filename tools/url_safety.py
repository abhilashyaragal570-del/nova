"""URL safety checks: keep tools from being tricked into reaching internal addresses (SSRF)."""
import ipaddress
import socket
from urllib.parse import urlsplit

ALLOWED_SCHEMES = {"http", "https"}
ALLOWED_PORTS = {80, 443}
MAX_URL_LENGTH = 2048


class UnsafeURL(ValueError):
    """Raised when a URL must not be fetched."""


def _check_ip(address: str) -> None:
    """Raise UnsafeURL unless `address` is a public internet address."""
    ip = ipaddress.ip_address(address.split("%")[0])  # drop IPv6 zone id
    if ip.version == 6 and ip.ipv4_mapped is not None:
        ip = ip.ipv4_mapped  # ::ffff:127.0.0.1 is really 127.0.0.1
    if not ip.is_global or ip.is_multicast:
        raise UnsafeURL(f"Address {ip} is not a public internet address")


def validate_url(url: str) -> str:
    """Return the cleaned URL if it is safe to fetch, otherwise raise UnsafeURL."""
    if not isinstance(url, str) or not url.strip():
        raise UnsafeURL("URL is empty")
    url = url.strip()
    if len(url) > MAX_URL_LENGTH:
        raise UnsafeURL("URL is too long")
    if any(ord(c) < 32 or ord(c) == 127 for c in url):
        raise UnsafeURL("URL contains control characters")

    try:
        parts = urlsplit(url)
        port = parts.port
    except ValueError as e:
        raise UnsafeURL(f"Malformed URL: {e}") from None

    if parts.scheme.lower() not in ALLOWED_SCHEMES:
        raise UnsafeURL(f"Scheme not allowed: {parts.scheme or '(none)'}")
    if parts.username is not None or parts.password is not None:
        raise UnsafeURL("Credentials in URLs are not allowed")
    host = parts.hostname
    if not host:
        raise UnsafeURL("URL has no host")
    if port is not None and port not in ALLOWED_PORTS:
        raise UnsafeURL(f"Port not allowed: {port}")

    effective_port = port or (443 if parts.scheme.lower() == "https" else 80)
    try:
        infos = socket.getaddrinfo(host, effective_port, type=socket.SOCK_STREAM)
    except socket.gaierror:
        raise UnsafeURL(f"Could not resolve host: {host}") from None
    if not infos:
        raise UnsafeURL(f"Could not resolve host: {host}")

    for info in infos:  # every address must be public, not just the first
        _check_ip(info[4][0])
    return url