"""Network settings for the Gemini client.

Two problems this fixes:
- The SDK sets no timeout, so a stuck connection can hang for minutes.
- Some networks advertise IPv6 but do not route it. The client then waits for
  each IPv6 address to fail before it tries IPv4.

By default requests are sent over IPv4 only, with a 60 second timeout.
Set NOVA_FORCE_IPV4=0 to switch the IPv4 setting off.
"""
import os

import httpx
from google.genai import types

DEFAULT_TIMEOUT_MS = 60_000
IPV4_ANY = "0.0.0.0"


def force_ipv4_enabled() -> bool:
    value = os.environ.get("NOVA_FORCE_IPV4", "1").strip().lower()
    return value not in {"0", "false", "no", "off"}


def build_http_options(
    timeout_ms: int = DEFAULT_TIMEOUT_MS, force_ipv4: bool | None = None
) -> types.HttpOptions:
    """HttpOptions with a timeout and, unless switched off, IPv4-only requests."""
    if force_ipv4 is None:
        force_ipv4 = force_ipv4_enabled()
    if not force_ipv4:
        return types.HttpOptions(timeout=timeout_ms)
    try:
        return types.HttpOptions(
            timeout=timeout_ms,
            client_args={"transport": httpx.HTTPTransport(local_address=IPV4_ANY)},
        )
    except Exception:
        # An older SDK without client_args: keep the timeout at least.
        return types.HttpOptions(timeout=timeout_ms)