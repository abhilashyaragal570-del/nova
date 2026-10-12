import pytest
from fastapi.testclient import TestClient

from web import fastapi_app

AUTH = ("nova", "secret")


@pytest.fixture
def client(monkeypatch, tmp_path):
    monkeypatch.setenv("NOVA_PASSWORD", "secret")
    log = tmp_path / "tool_usage.jsonl"
    log.write_text("", encoding="utf-8")
    monkeypatch.setattr(fastapi_app, "get_log_path", lambda: log)
    return TestClient(fastapi_app.app)


def test_usage_api_needs_the_password(client):
    res = client.get("/api/usage")
    assert res.status_code == 401
    assert "Basic" in res.headers["www-authenticate"]


def test_usage_api_returns_a_summary(client):
    res = client.get("/api/usage", auth=AUTH)
    assert res.status_code == 200
    body = res.json()
    assert isinstance(body, dict)
    assert body["skipped"] == 0


def test_usage_api_is_listed_in_docs_but_the_page_is_not(client):
    paths = client.get("/openapi.json").json()["paths"]
    assert "/api/usage" in paths
    # The /usage page is still served by Flask, so FastAPI doesn't list it.
    assert "/usage" not in paths


def test_usage_page_is_still_served_by_flask(client):
    res = client.get("/usage", auth=AUTH)
    assert res.status_code == 200
    assert "text/html" in res.headers["content-type"]