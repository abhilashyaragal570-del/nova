import json

import pytest
from fastapi.testclient import TestClient

from web import fastapi_app

PASSWORD = "test-password"
AUTH = ("user", PASSWORD)


def entry(tool="calculator", tokens=10, source="web"):
    return {
        "source": source,
        "tools": [tool],
        "tool_calls": 1,
        "hit_round_limit": False,
        "total_tokens": tokens,
    }


def write(path, *entries):
    path.write_text("".join(json.dumps(e) + "\n" for e in entries), encoding="utf-8")


@pytest.fixture
def client(monkeypatch, tmp_path):
    monkeypatch.setenv("NOVA_PASSWORD", PASSWORD)
    log = tmp_path / "usage.jsonl"
    entries = [
        {
            "source": "web",
            "tools": ["calculator"],
            "tool_calls": 1,
            "hit_round_limit": False,
            "total_tokens": 100,
        },
        {
            "source": "terminal",
            "tools": [],
            "tool_calls": 0,
            "hit_round_limit": False,
            "total_tokens": 50,
        },
    ]
    log.write_text(
        "\n".join(json.dumps(e) for e in entries) + "\nnot json\n", encoding="utf-8"
    )
    monkeypatch.setenv("TOOL_LOG_PATH", str(log))
    return TestClient(fastapi_app.app)


def test_usage_api_needs_the_password(client):
    res = client.get("/api/usage")
    assert res.status_code == 401
    assert "Basic" in res.headers["www-authenticate"]


def test_usage_api_returns_the_summary(client):
    res = client.get("/api/usage", auth=AUTH)
    assert res.status_code == 200
    data = res.json()
    assert data["turns"] == 2
    assert data["total_tokens"] == 150
    assert data["no_tool_turns"] == 1
    assert data["tools"] == {"calculator": 1}
    assert data["sources"]["web"] == {"turns": 1, "tokens": 100}
    assert data["skipped"] == 1


def test_usage_api_with_no_log_file_is_empty(monkeypatch, tmp_path):
    monkeypatch.setenv("NOVA_PASSWORD", PASSWORD)
    monkeypatch.setenv("TOOL_LOG_PATH", str(tmp_path / "missing.jsonl"))
    res = TestClient(fastapi_app.app).get("/api/usage", auth=AUTH)
    assert res.status_code == 200
    assert res.json()["turns"] == 0


def test_usage_api_includes_the_older_log(monkeypatch, tmp_path):
    monkeypatch.setenv("NOVA_PASSWORD", PASSWORD)
    log = tmp_path / "usage.jsonl"
    write(tmp_path / "usage.jsonl.1", entry("old", tokens=10))
    write(log, entry("new", tokens=5))
    monkeypatch.setenv("TOOL_LOG_PATH", str(log))
    data = TestClient(fastapi_app.app).get("/api/usage", auth=AUTH).json()
    assert data["turns"] == 2
    assert data["total_tokens"] == 15


def test_usage_api_is_listed_in_docs_but_the_page_is_not(client):
    paths = client.get("/openapi.json", auth=AUTH).json()["paths"]
    assert "/api/usage" in paths
    # The /usage page is still served by Flask, so FastAPI doesn't list it.
    assert "/usage" not in paths


def test_usage_page_is_served(client):
    res = client.get("/usage", auth=AUTH)
    assert res.status_code == 200
    assert "text/html" in res.headers["content-type"]
    assert b"Nova tool usage" in res.content


def test_usage_page_needs_the_password(client):
    assert client.get("/usage").status_code == 401