import ipaddress
import socket

import pytest
import requests

from tools.api_request import (
    MAX_OUTPUT_CHARS,
    MAX_RESPONSE_BYTES,
    TIMEOUT_SECONDS,
    ApiRequestTool,
)
from tools.policy import ToolPolicy
from tools.registry import ToolRegistry

PUBLIC = "93.184.216.34"


@pytest.fixture(autouse=True)
def fake_dns(monkeypatch):
    table = {
        "example.com": [PUBLIC],
        "other.example": [PUBLIC],
        "evil.example": ["127.0.0.1"],
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


class FakeResponse:
    def __init__(self, status=200, headers=None, body=b'{"ok": true}', encoding="utf-8"):
        self.status_code = status
        self.headers = headers if headers is not None else {"Content-Type": "application/json"}
        self._body = body
        self.encoding = encoding
        self.closed = False

    def iter_content(self, chunk_size=8192):
        for i in range(0, len(self._body), chunk_size):
            yield self._body[i : i + chunk_size]

    def close(self):
        self.closed = True


class FakeSession:
    def __init__(self, *responses):
        self.responses = list(responses)
        self.calls = []

    def request(self, method, url, **kwargs):
        self.calls.append((method, url, kwargs))
        item = self.responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


def redirect(location, status=302):
    return FakeResponse(status, {"Location": location}, b"")


def test_get_returns_body():
    session = FakeSession(FakeResponse(body=b'{"hello": "world"}'))
    result = ApiRequestTool(session=session).run(url="https://example.com/data")
    assert result.ok
    assert result.output["status"] == 200
    assert result.output["body"] == '{"hello": "world"}'
    assert result.output["truncated"] is False
    assert session.calls[0][0] == "GET"


def test_post_sends_json_body_and_header():
    session = FakeSession(FakeResponse())
    result = ApiRequestTool(session=session).run(
        url="https://example.com/x", method="post", body='{"a": 1}'
    )
    assert result.ok
    method, _, kwargs = session.calls[0]
    assert method == "POST"
    assert kwargs["data"] == b'{"a": 1}'
    assert kwargs["headers"]["Content-Type"] == "application/json"


def test_get_with_body_is_refused():
    session = FakeSession()
    result = ApiRequestTool(session=session).run(url="https://example.com/", body='{"a": 1}')
    assert not result.ok
    assert session.calls == []


@pytest.mark.parametrize("method", ["DELETE", "PUT", "PATCH"])
def test_other_methods_are_refused(method):
    session = FakeSession()
    result = ApiRequestTool(session=session).run(url="https://example.com/", method=method)
    assert not result.ok
    assert session.calls == []


def test_invalid_json_body_is_refused():
    session = FakeSession()
    result = ApiRequestTool(session=session).run(
        url="https://example.com/", method="POST", body="{not json"
    )
    assert not result.ok and "JSON" in result.error
    assert session.calls == []


def test_missing_url_is_refused():
    result = ApiRequestTool(session=FakeSession()).run(url=None)
    assert not result.ok


@pytest.mark.parametrize("url", [
    "http://127.0.0.1/",
    "http://169.254.169.254/latest/meta-data/",
    "http://evil.example/",
])
def test_unsafe_url_is_blocked_before_any_request(url):
    session = FakeSession()
    result = ApiRequestTool(session=session).run(url=url)
    assert not result.ok and "Blocked URL" in result.error
    assert session.calls == []


def test_redirect_is_followed():
    session = FakeSession(redirect("https://other.example/final"), FakeResponse())
    result = ApiRequestTool(session=session).run(url="https://example.com/start")
    assert result.ok
    assert [c[1] for c in session.calls] == ["https://example.com/start", "https://other.example/final"]


def test_relative_redirect_is_followed():
    session = FakeSession(redirect("/v2/data", 301), FakeResponse())
    result = ApiRequestTool(session=session).run(url="https://example.com/v1/data")
    assert result.ok
    assert session.calls[1][1] == "https://example.com/v2/data"


def test_redirect_to_internal_address_is_blocked():
    session = FakeSession(redirect("http://127.0.0.1/admin"))
    result = ApiRequestTool(session=session).run(url="https://example.com/start")
    assert not result.ok and "Redirect blocked" in result.error
    assert len(session.calls) == 1


def test_too_many_redirects():
    session = FakeSession(*[redirect("https://example.com/again") for _ in range(6)])
    result = ApiRequestTool(session=session).run(url="https://example.com/start")
    assert not result.ok and "Too many redirects" in result.error
    assert len(session.calls) == 4  # first request plus 3 redirects


def test_post_redirect_is_refused():
    session = FakeSession(redirect("https://other.example/", 307))
    result = ApiRequestTool(session=session).run(
        url="https://example.com/", method="POST", body='{"a": 1}'
    )
    assert not result.ok
    assert len(session.calls) == 1


def test_html_response_is_refused():
    session = FakeSession(FakeResponse(headers={"Content-Type": "text/html"}, body=b"<html></html>"))
    result = ApiRequestTool(session=session).run(url="https://example.com/")
    assert not result.ok and "Content type" in result.error


def test_json_suffix_content_type_is_allowed():
    session = FakeSession(FakeResponse(headers={"Content-Type": "application/problem+json; charset=utf-8"}))
    assert ApiRequestTool(session=session).run(url="https://example.com/").ok


def test_oversized_response_is_refused():
    big = b"x" * (MAX_RESPONSE_BYTES + 1)
    session = FakeSession(FakeResponse(headers={"Content-Type": "text/plain"}, body=big))
    result = ApiRequestTool(session=session).run(url="https://example.com/")
    assert not result.ok and "too large" in result.error


def test_long_text_is_truncated():
    body = b"a" * (MAX_OUTPUT_CHARS + 10)
    session = FakeSession(FakeResponse(headers={"Content-Type": "text/plain"}, body=body))
    result = ApiRequestTool(session=session).run(url="https://example.com/")
    assert result.ok
    assert len(result.output["body"]) == MAX_OUTPUT_CHARS
    assert result.output["truncated"] is True


def test_http_error_status_is_a_failure():
    session = FakeSession(FakeResponse(status=404))
    result = ApiRequestTool(session=session).run(url="https://example.com/missing")
    assert not result.ok and "404" in result.error


def test_timeout_is_a_failure():
    session = FakeSession(requests.Timeout())
    result = ApiRequestTool(session=session).run(url="https://example.com/")
    assert not result.ok and "timed out" in result.error


def test_connection_error_is_a_failure():
    session = FakeSession(requests.ConnectionError())
    result = ApiRequestTool(session=session).run(url="https://example.com/")
    assert not result.ok and "connect" in result.error


def test_request_never_auto_redirects_and_sets_no_credentials():
    session = FakeSession(FakeResponse())
    ApiRequestTool(session=session).run(url="https://example.com/")
    kwargs = session.calls[0][2]
    assert kwargs["allow_redirects"] is False
    assert kwargs["stream"] is True
    assert kwargs["timeout"] == TIMEOUT_SECONDS
    assert "Authorization" not in kwargs["headers"]


def test_tool_needs_confirmation_through_the_registry():
    session = FakeSession(FakeResponse())
    tool = ApiRequestTool(session=session)
    assert tool.read_only is False

    declined = ToolRegistry(policy=ToolPolicy(confirm=lambda name, args: False))
    declined.register(tool)
    assert not declined.execute("api_request", {"url": "https://example.com/"}).ok
    assert session.calls == []  # refused before any request was made

    approved = ToolRegistry(policy=ToolPolicy(confirm=lambda name, args: True))
    approved.register(tool)
    assert approved.execute("api_request", {"url": "https://example.com/"}).ok