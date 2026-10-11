import base64
import json

import pytest

from web import server

PASSWORD = "test-password"


@pytest.fixture
def client(monkeypatch, tmp_path):
    monkeypatch.setenv("NOVA_PASSWORD", PASSWORD)
    log = tmp_path / "usage.jsonl"
    entries = [
        {"source": "web", "tools": ["calculator"], "tool_calls": 1,
         "hit_round_limit": False, "total_tokens": 100},
        {"source": "terminal", "tools": [], "tool_calls": 0,
         "hit_round_limit": False, "total_tokens": 50},
    ]
    log.write_text(
        "\n".join(json.dumps(e) for e in entries) + "\nnot json\n", encoding="utf-8"
    )
    monkeypatch.setenv("TOOL_LOG_PATH", str(log))
    return server.app.test_client()


def auth():
    token = base64.b64encode(f"user:{PASSWORD}".encode()).decode()
    return {"Authorization": f"Basic {token}"}


def test_api_usage_returns_the_summary(client):
    response = client.get("/api/usage", headers=auth())
    assert response.status_code == 200
    data = response.get_json()
    assert data["turns"] == 2
    assert data["total_tokens"] == 150
    assert data["no_tool_turns"] == 1
    assert data["tools"] == {"calculator": 1}
    assert data["sources"]["web"] == {"turns": 1, "tokens": 100}
    assert data["skipped"] == 1


def test_api_usage_needs_the_password(client):
    assert client.get("/api/usage").status_code == 401


def test_usage_page_is_served(client):
    response = client.get("/usage", headers=auth())
    assert response.status_code == 200
    assert b"Nova tool usage" in response.data
    response.close()


def test_usage_page_needs_the_password(client):
    assert client.get("/usage").status_code == 401


def test_api_usage_with_no_log_file_is_empty(monkeypatch, tmp_path):
    monkeypatch.setenv("NOVA_PASSWORD", PASSWORD)
    monkeypatch.setenv("TOOL_LOG_PATH", str(tmp_path / "missing.jsonl"))
    response = server.app.test_client().get("/api/usage", headers=auth())
    assert response.status_code == 200
    assert response.get_json()["turns"] == 0