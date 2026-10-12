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


def test_refuses_everything_when_no_password_is_set(client, monkeypatch):
    monkeypatch.delenv("NOVA_PASSWORD", raising=False)
    res = client.get("/memory", auth=AUTH)
    assert res.status_code == 503
    assert "NOVA_PASSWORD" in res.json()["error"]


def test_requires_a_login(client):
    res = client.get("/memory")
    assert res.status_code == 401
    assert "Basic" in res.headers["www-authenticate"]


def test_wrong_password_is_refused(client):
    assert client.get("/memory", auth=("nova", "nope")).status_code == 401


def test_list_is_empty_at_first(client):
    res = client.get("/memory", auth=AUTH)
    assert res.status_code == 200
    assert res.json() == []


def test_add_then_list(client):
    res = client.post("/memory", json={"fact": "I like tea"}, auth=AUTH)
    assert res.status_code == 201
    fact = res.json()
    assert fact["text"] == "I like tea"
    assert fact["id"]
    assert client.get("/memory", auth=AUTH).json()[0]["id"] == fact["id"]


def test_a_repeated_fact_is_saved_once(client):
    client.post("/memory", json={"fact": "I like tea"}, auth=AUTH)
    client.post("/memory", json={"fact": "i like TEA"}, auth=AUTH)
    assert len(client.get("/memory", auth=AUTH).json()) == 1


def test_empty_fact_is_refused(client):
    res = client.post("/memory", json={"fact": "   "}, auth=AUTH)
    assert res.status_code == 400
    assert res.json() == {"error": "fact must not be empty"}


def test_missing_or_non_text_fact_is_refused(client):
    for body in ({}, {"fact": 123}, {"fact": None}, {"other": "x"}):
        res = client.post("/memory", json=body, auth=AUTH)
        assert res.status_code == 400
        assert res.json() == {"error": "fact must be text"}


def test_too_long_fact_is_refused(client):
    res = client.post("/memory", json={"fact": "x" * 201}, auth=AUTH)
    assert res.status_code == 400
    assert "too long" in res.json()["error"]


def test_full_memory_is_refused(client, monkeypatch, tmp_path):
    monkeypatch.setattr(
        fastapi_app, "fact_store", FactStore(tmp_path / "small.json", max_facts=1)
    )
    assert client.post("/memory", json={"fact": "one"}, auth=AUTH).status_code == 201
    res = client.post("/memory", json={"fact": "two"}, auth=AUTH)
    assert res.status_code == 400
    assert "memory is full" in res.json()["error"]


def test_save_failure_gives_503(client, monkeypatch):
    def boom(text):
        raise OSError("disk")

    monkeypatch.setattr(fastapi_app.fact_store, "add", boom)
    res = client.post("/memory", json={"fact": "I like tea"}, auth=AUTH)
    assert res.status_code == 503
    assert res.json() == {"error": "Could not save the fact"}


def test_delete_a_fact(client):
    fact = client.post("/memory", json={"fact": "I like tea"}, auth=AUTH).json()
    res = client.delete("/memory/" + fact["id"], auth=AUTH)
    assert res.status_code == 200
    assert res.json() == {"ok": True}
    assert client.get("/memory", auth=AUTH).json() == []


def test_delete_unknown_id_is_404(client):
    res = client.delete("/memory/nope", auth=AUTH)
    assert res.status_code == 404
    assert res.json() == {"error": "Not found"}


def test_docs_page_and_schema_exist(client):
    assert client.get("/docs", auth=AUTH).status_code == 200
    paths = client.get("/openapi.json", auth=AUTH).json()["paths"]
    assert "/memory" in paths
    assert "/memory/{fact_id}" in paths