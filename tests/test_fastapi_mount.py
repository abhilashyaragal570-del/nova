import pytest
from fastapi.testclient import TestClient

from memory.fact_store import FactStore
from web import fastapi_app

AUTH = ("nova", "secret")


@pytest.fixture
def client(monkeypatch, tmp_path):
    monkeypatch.setenv("NOVA_PASSWORD", "secret")
    monkeypatch.setattr(fastapi_app, "fact_store", FactStore(tmp_path / "facts.json"))
    return TestClient(fastapi_app.app)


def test_the_chat_page_is_served_by_flask_through_fastapi(client):
    res = client.get("/", auth=AUTH)
    assert res.status_code == 200
    assert 'id="memtoggle"' in res.text


def test_flask_routes_still_need_the_password(client):
    res = client.get("/usage")
    assert res.status_code == 401
    assert "Basic" in res.headers["www-authenticate"]


def test_flask_routes_work_with_the_password(client):
    res = client.get("/usage", auth=AUTH)
    assert res.status_code == 200


def test_flask_refuses_everything_when_no_password_is_set(client, monkeypatch):
    monkeypatch.delenv("NOVA_PASSWORD", raising=False)
    res = client.get("/usage", auth=AUTH)
    assert res.status_code == 503


def test_flask_usage_page_is_html(client):
    res = client.get("/usage", auth=AUTH)
    assert "text/html" in res.headers["content-type"]


def test_memory_is_answered_by_fastapi_not_flask(client):
    paths = client.get("/openapi.json").json()["paths"]
    assert "/memory" in paths
    # /chat and the /usage page are still Flask, so FastAPI doesn't list them.
    assert "/usage" not in paths
    assert "/chat" not in paths
    res = client.post("/memory", json={"fact": "I like tea"}, auth=AUTH)
    assert res.status_code == 201
    # The test store was used, so FastAPI's route (not Flask's) handled it.
    assert client.get("/memory", auth=AUTH).json()[0]["text"] == "I like tea"


def test_docs_still_work_after_mounting(client):
    assert client.get("/docs").status_code == 200