import base64

import pytest

from app import chat as chat_module
from memory.fact_store import FactStore
from web import server


def basic(pw):
    token = base64.b64encode(f"nova:{pw}".encode()).decode()
    return {"Authorization": "Basic " + token}


AUTH = basic("secret")


@pytest.fixture
def setup(monkeypatch, tmp_path):
    monkeypatch.setenv("NOVA_PASSWORD", "secret")
    facts = FactStore(tmp_path / "facts.json")
    monkeypatch.setattr(server, "fact_store", facts)
    return server.app.test_client(), facts


def test_routes_require_the_password(setup):
    client, _ = setup
    assert client.get("/memory").status_code == 401
    assert client.post("/memory", json={"fact": "x"}).status_code == 401
    assert client.delete("/memory/abc").status_code == 401


def test_list_is_empty_at_first(setup):
    client, _ = setup
    res = client.get("/memory", headers=AUTH)
    assert res.status_code == 200
    assert res.get_json() == []


def test_add_then_list(setup):
    client, facts = setup
    res = client.post("/memory", json={"fact": "Likes tea"}, headers=AUTH)
    assert res.status_code == 201
    saved = res.get_json()
    assert saved["text"] == "Likes tea"
    listed = client.get("/memory", headers=AUTH).get_json()
    assert [f["text"] for f in listed] == ["Likes tea"]
    assert listed[0]["id"] == saved["id"]
    assert [f["text"] for f in facts.list()] == ["Likes tea"]


def test_add_rejects_an_empty_fact(setup):
    client, facts = setup
    res = client.post("/memory", json={"fact": "   "}, headers=AUTH)
    assert res.status_code == 400
    assert "empty" in res.get_json()["error"]
    assert facts.list() == []


def test_add_rejects_a_missing_or_non_text_fact(setup):
    client, facts = setup
    assert client.post("/memory", json={}, headers=AUTH).status_code == 400
    assert client.post("/memory", json={"fact": 42}, headers=AUTH).status_code == 400
    assert facts.list() == []


def test_adding_the_same_fact_twice_keeps_one(setup):
    client, facts = setup
    first = client.post("/memory", json={"fact": "Likes tea"}, headers=AUTH).get_json()
    second = client.post("/memory", json={"fact": "likes TEA"}, headers=AUTH).get_json()
    assert second["id"] == first["id"]
    assert len(facts.list()) == 1


def test_a_full_memory_is_a_400_with_a_message(monkeypatch, tmp_path):
    monkeypatch.setenv("NOVA_PASSWORD", "secret")
    monkeypatch.setattr(server, "fact_store", FactStore(tmp_path / "f.json", max_facts=1))
    client = server.app.test_client()
    assert client.post("/memory", json={"fact": "one"}, headers=AUTH).status_code == 201
    res = client.post("/memory", json={"fact": "two"}, headers=AUTH)
    assert res.status_code == 400
    assert "full" in res.get_json()["error"]


def test_delete_removes_a_fact(setup):
    client, facts = setup
    keep = facts.add("keep me")
    drop = facts.add("drop me")
    res = client.delete(f"/memory/{drop['id']}", headers=AUTH)
    assert res.status_code == 200
    assert [f["id"] for f in facts.list()] == [keep["id"]]


def test_delete_unknown_id_is_404(setup):
    client, facts = setup
    facts.add("keep me")
    res = client.delete("/memory/nope", headers=AUTH)
    assert res.status_code == 404
    assert len(facts.list()) == 1


def test_the_web_routes_use_the_same_store_as_nova_s_tools():
    assert server.fact_store is chat_module.fact_store