import json
import threading
import time
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from memory.conversation_store import ConversationStore
from web import fastapi_app, server
from web.approvals import ApprovalBroker

AUTH = ("nova", "secret")


class FakeChunk:
    def __init__(self, text):
        self.text = text
        self.usage_metadata = None
        part = SimpleNamespace(text=text, function_call=None)
        content = SimpleNamespace(parts=[part])
        self.candidates = [SimpleNamespace(content=content)]


class FakeSession:
    def send_message_stream(self, message):
        yield FakeChunk("Hello ")
        yield FakeChunk("there")


@pytest.fixture
def broker(monkeypatch):
    broker = ApprovalBroker(timeout=5)
    monkeypatch.setattr(server, "approvals", broker)
    return broker


@pytest.fixture
def anon_client(tmp_path, monkeypatch, broker):
    # Send every file Nova writes into a temp folder, and never call Gemini
    monkeypatch.setattr(
        server,
        "store",
        ConversationStore(tmp_path / "conversations", tmp_path / "history.json"),
    )
    monkeypatch.setattr(server, "PROMPT_FILE", tmp_path / "personality.json")
    monkeypatch.setattr(server, "current_prompt", "Original prompt")
    monkeypatch.setattr(server, "log_turn", lambda *a, **k: True)
    monkeypatch.setenv("NOVA_PASSWORD", "secret")
    return TestClient(fastapi_app.app)


@pytest.fixture
def client(anon_client):
    anon_client.auth = AUTH
    return anon_client


def _start(broker):
    result = []
    t = threading.Thread(
        target=lambda: result.append(broker.confirm("write_file", {"path": "a.txt"}))
    )
    t.start()
    return t, result


def _wait_for_pending(broker):
    for _ in range(300):
        pending = broker.list_pending()
        if pending:
            return pending
        time.sleep(0.01)
    raise AssertionError("no pending approval appeared")


def test_routes_need_the_password(anon_client):
    for path in ("/system", "/conversations", "/conversations/main", "/approvals"):
        assert anon_client.get(path).status_code == 401
    assert anon_client.post("/system", json={"prompt": "x"}).status_code == 401
    assert anon_client.post("/conversations").status_code == 401
    assert anon_client.delete("/conversations/main").status_code == 401
    assert anon_client.post("/approvals/abc", json={"approved": True}).status_code == 401
    assert anon_client.get("/system", auth=("nova", "wrong")).status_code == 401


def test_routes_refuse_everything_when_no_password_is_set(anon_client, monkeypatch):
    monkeypatch.delenv("NOVA_PASSWORD", raising=False)
    for path in ("/system", "/conversations", "/approvals"):
        assert anon_client.get(path, auth=AUTH).status_code == 503


def test_system_roundtrip(client):
    assert client.get("/system").json() == {"prompt": "Original prompt"}
    res = client.post("/system", json={"prompt": "  You are a pirate.  "})
    assert res.status_code == 200
    assert res.json() == {"prompt": "You are a pirate."}
    assert client.get("/system").json() == {"prompt": "You are a pirate."}


def test_system_is_saved_to_the_file(client, tmp_path):
    client.post("/system", json={"prompt": "You are a pirate."})
    saved = json.loads((tmp_path / "personality.json").read_text(encoding="utf-8"))
    assert saved == {"prompt": "You are a pirate."}


def test_system_rejects_empty(client):
    res = client.post("/system", json={"prompt": "   "})
    assert res.status_code == 400
    assert res.json() == {"error": "Empty personality"}


def test_system_rejects_missing_or_non_text(client):
    for body in ({}, {"prompt": None}, {"prompt": 5}, {"other": "x"}):
        res = client.post("/system", json=body)
        assert res.status_code == 400
        assert res.json() == {"error": "Empty personality"}


def test_system_save_failure_gives_503_and_keeps_the_old_prompt(client, monkeypatch):
    def boom(prompt):
        raise OSError("disk")

    monkeypatch.setattr(server, "save_prompt", boom)
    res = client.post("/system", json={"prompt": "You are a pirate."})
    assert res.status_code == 503
    assert res.json() == {"error": "Could not save the personality"}
    assert client.get("/system").json() == {"prompt": "Original prompt"}


def test_the_chat_uses_the_personality_set_through_fastapi(client, monkeypatch):
    seen = []

    def fake_new_chat(messages, prompt):
        seen.append(prompt)
        return FakeSession()

    monkeypatch.setattr(server, "new_chat", fake_new_chat)
    client.post("/system", json={"prompt": "You are a pirate."})
    res = client.post("/chat", json={"message": "hi"})
    assert res.status_code == 200
    assert res.text == "Hello there"
    assert seen == ["You are a pirate."]


def test_list_has_main_chat(client):
    items = client.get("/conversations").json()
    assert items[0] == {"id": "main", "title": "Main chat"}


def test_create_and_get_conversation(client):
    created = client.post("/conversations").json()
    assert created["id"]
    assert created["title"]
    res = client.get("/conversations/" + created["id"])
    assert res.status_code == 200
    assert res.json()["messages"] == []
    ids = [c["id"] for c in client.get("/conversations").json()]
    assert created["id"] in ids


def test_get_unknown_conversation_is_404(client):
    res = client.get("/conversations/aaaaaaaaaaaa")
    assert res.status_code == 404
    assert res.json() == {"error": "Not found"}


def test_invalid_id_is_rejected(client):
    assert client.get("/conversations/not-valid").status_code == 404
    assert client.delete("/conversations/not-valid").status_code == 404


def test_delete_conversation(client):
    cid = client.post("/conversations").json()["id"]
    res = client.delete("/conversations/" + cid)
    assert res.status_code == 200
    assert res.json() == {"ok": True}
    assert client.get("/conversations/" + cid).status_code == 404


def test_deleting_a_well_formed_id_that_does_not_exist_is_ok(client):
    # The store treats this delete as done, and the Flask route did the same.
    # A malformed id is the case that gives 404 (see test_invalid_id_is_rejected).
    res = client.delete("/conversations/aaaaaaaaaaaa")
    assert res.status_code == 200
    assert res.json() == {"ok": True}


def test_approvals_list_is_empty_when_nothing_is_waiting(client):
    res = client.get("/approvals")
    assert res.status_code == 200
    assert res.json() == []


def test_approvals_unknown_id_is_404(client):
    res = client.post("/approvals/nope", json={"approved": True})
    assert res.status_code == 404
    assert res.json() == {"error": "Unknown or already answered"}


def test_approve_through_the_route(client, broker):
    t, result = _start(broker)
    pending = _wait_for_pending(broker)
    listed = client.get("/approvals").json()
    assert listed[0]["tool"] == "write_file"
    res = client.post(f"/approvals/{pending[0]['id']}", json={"approved": True})
    assert res.status_code == 200
    assert res.json() == {"ok": True}
    t.join(2)
    assert result == [True]


def test_anything_but_true_denies(client, broker):
    t, result = _start(broker)
    pending = _wait_for_pending(broker)
    client.post(f"/approvals/{pending[0]['id']}", json={"approved": "yes"})
    t.join(2)
    assert result == [False]


def test_an_answer_with_no_body_denies(client, broker):
    t, result = _start(broker)
    pending = _wait_for_pending(broker)
    res = client.post(f"/approvals/{pending[0]['id']}")
    assert res.status_code == 200
    t.join(2)
    assert result == [False]


def test_the_new_routes_are_listed_in_docs(client):
    paths = client.get("/openapi.json").json()["paths"]
    for path in (
        "/system",
        "/conversations",
        "/conversations/{cid}",
        "/approvals",
        "/approvals/{approval_id}",
    ):
        assert path in paths