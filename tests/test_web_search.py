import requests

from tools.registry import ToolRegistry
from tools.web_search import (
    MAX_QUERY_LENGTH,
    MAX_RESULTS_LIMIT,
    MAX_SNIPPET_LENGTH,
    WebSearchTool,
)

FAKE_KEY = "tvly-fake-test-key"


class FakeResponse:
    def __init__(self, status_code=200, payload=None, bad_json=False):
        self.status_code = status_code
        self._payload = payload
        self._bad_json = bad_json

    def json(self):
        if self._bad_json:
            raise ValueError("not json")
        return self._payload


class FakeSession:
    """Stands in for requests: records the call, returns or raises on demand."""

    def __init__(self, response=None, error=None):
        self.response = response
        self.error = error
        self.calls = []

    def post(self, url, **kwargs):
        self.calls.append((url, kwargs))
        if self.error:
            raise self.error
        return self.response


def make_tool(response=None, error=None):
    session = FakeSession(response=response, error=error)
    return WebSearchTool(api_key=FAKE_KEY, session=session), session


def good_payload(n=3):
    return {
        "results": [
            {"title": f"Title {i}", "url": f"https://example.com/{i}", "content": f"Snippet {i}"}
            for i in range(n)
        ]
    }


# ---------- success ----------

def test_successful_search_returns_structured_results():
    tool, _ = make_tool(FakeResponse(200, good_payload(3)))
    result = tool.run(query="latest python version")
    assert result.ok
    assert result.output[0] == {
        "title": "Title 0",
        "url": "https://example.com/0",
        "snippet": "Snippet 0",
    }
    assert len(result.output) == 3


def test_request_uses_timeout_and_auth_header():
    tool, session = make_tool(FakeResponse(200, good_payload()))
    tool.run(query="python")
    _, kwargs = session.calls[0]
    assert kwargs["timeout"] > 0
    assert kwargs["headers"]["Authorization"] == f"Bearer {FAKE_KEY}"


def test_max_results_is_clamped():
    tool, session = make_tool(FakeResponse(200, good_payload()))
    tool.run(query="python", max_results=999)
    assert session.calls[0][1]["json"]["max_results"] == MAX_RESULTS_LIMIT
    tool.run(query="python", max_results=-5)
    assert session.calls[1][1]["json"]["max_results"] == 1


def test_long_snippet_is_truncated():
    payload = {"results": [{"title": "t", "url": "u", "content": "x" * 5000}]}
    tool, _ = make_tool(FakeResponse(200, payload))
    result = tool.run(query="python")
    assert len(result.output[0]["snippet"]) == MAX_SNIPPET_LENGTH


def test_empty_results_is_success():
    tool, _ = make_tool(FakeResponse(200, {"results": []}))
    result = tool.run(query="zzzz")
    assert result.ok and result.output == []


# ---------- input validation ----------

def test_empty_query_rejected():
    tool, session = make_tool(FakeResponse(200, good_payload()))
    assert not tool.run(query="").ok
    assert not tool.run(query="   ").ok
    assert not tool.run(query=None).ok
    assert session.calls == []  # never reached the network


def test_overlong_query_rejected():
    tool, session = make_tool(FakeResponse(200, good_payload()))
    result = tool.run(query="a" * (MAX_QUERY_LENGTH + 1))
    assert not result.ok and "too long" in result.error.lower()
    assert session.calls == []


def test_missing_api_key(monkeypatch):
    monkeypatch.delenv("TAVILY_API_KEY", raising=False)
    tool = WebSearchTool(api_key=None, session=FakeSession(FakeResponse(200, good_payload())))
    result = tool.run(query="python")
    assert not result.ok and "TAVILY_API_KEY" in result.error


# ---------- failures ----------

def test_timeout_is_handled():
    tool, _ = make_tool(error=requests.Timeout())
    result = tool.run(query="python")
    assert not result.ok and "timed out" in result.error.lower()


def test_connection_error_is_handled():
    tool, _ = make_tool(error=requests.ConnectionError())
    result = tool.run(query="python")
    assert not result.ok and "reach" in result.error.lower()


def test_other_request_error_is_handled():
    tool, _ = make_tool(error=requests.RequestException("weird"))
    assert not tool.run(query="python").ok


def test_bad_key_status():
    tool, _ = make_tool(FakeResponse(401, {}))
    result = tool.run(query="python")
    assert not result.ok and "key" in result.error.lower()


def test_rate_limit_status():
    tool, _ = make_tool(FakeResponse(429, {}))
    result = tool.run(query="python")
    assert not result.ok and "rate limit" in result.error.lower()


def test_server_error_status():
    tool, _ = make_tool(FakeResponse(500, {}))
    result = tool.run(query="python")
    assert not result.ok and "500" in result.error


def test_unreadable_json():
    tool, _ = make_tool(FakeResponse(200, bad_json=True))
    assert not tool.run(query="python").ok


def test_unexpected_result_format():
    tool, _ = make_tool(FakeResponse(200, {"results": "not a list"}))
    assert not tool.run(query="python").ok


def test_malformed_items_are_skipped():
    payload = {"results": ["junk", 5, {"title": "ok", "url": "u", "content": "c"}]}
    tool, _ = make_tool(FakeResponse(200, payload))
    result = tool.run(query="python")
    assert result.ok and len(result.output) == 1


# ---------- security ----------

def test_api_key_never_appears_in_errors():
    for response in (FakeResponse(401, {}), FakeResponse(429, {}), FakeResponse(500, {})):
        tool, _ = make_tool(response)
        assert FAKE_KEY not in (tool.run(query="python").error or "")


# ---------- works through the registry ----------

def test_works_through_registry():
    tool, _ = make_tool(FakeResponse(200, good_payload(2)))
    reg = ToolRegistry()
    reg.register(tool)
    result = reg.execute("web_search", {"query": "python"})
    assert result.ok and len(result.output) == 2


def test_registry_reports_missing_query():
    tool, _ = make_tool(FakeResponse(200, good_payload()))
    reg = ToolRegistry()
    reg.register(tool)
    result = reg.execute("web_search", {})
    assert not result.ok and "query" in result.error