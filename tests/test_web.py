import base64
import json

import pytest

from web import server
from app import chat as chat_module


class FakeChunk:
    def __init__(self, text):
        self.text = text
        self.usage_metadata = None


class FakeSession:
    def send_message_stream(self, message):
        yield FakeChunk("Hello ")
        yield FakeChunk("there")


@pytest.fixture
def client(tmp_path, monkeypatch):
    # Send every file Nova writes into a temp folder
    monkeypatch.setattr(server, "CONV_DIR", tmp_path / "conversations")
    monkeypatch.setattr(server, "PROMPT_FILE", tmp_path / "personality.json")
    history = tmp_path / "history.json"
    monkeypatch.setattr(server, "HISTORY_FILE", history)
    monkeypatch.setattr(chat_module, "HISTORY_FILE", history)
    # Never call Gemini
    monkeypatch.setattr(server, "new_chat", lambda messages, prompt: FakeSession())
    # Keep a real NOVA_PASSWORD from your environment out of the tests
    monkeypatch.delenv("NOVA_PASSWORD", raising=False)
    server.app.config["TESTING"] = True
    return server.app.test_client()


def basic(pw):
    token = base64.b64encode(f"nova:{pw}".encode()).decode()
    return {"Authorization": "Basic " + token}


def test_system_roundtrip(client):
    r = client.post("/system", json={"prompt": "You are a pirate."})
    assert r.status_code == 200
    assert client.get("/system").get_json()["prompt"] == "You are a pirate."


def test_system_rejects_empty(client):
    r = client.post("/system", json={"prompt": "   "})
    assert r.status_code == 400


def test_list_has_main_chat(client):
    items = client.get("/conversations").get_json()
    assert items[0] == {"id": "main", "title": "Main chat"}


def test_create_and_get_conversation(client):
    created = client.post("/conversations").get_json()
    r = client.get("/conversations/" + created["id"])
    assert r.status_code == 200
    assert r.get_json()["messages"] == []


def test_get_unknown_conversation_is_404(client):
    assert client.get("/conversations/aaaaaaaaaaaa").status_code == 404


def test_invalid_id_is_rejected(client):
    assert client.get("/conversations/not-valid").status_code == 404
    assert client.delete("/conversations/not-valid").status_code == 404


def test_chat_streams_and_saves(client):
    cid = client.post("/conversations").get_json()["id"]
    r = client.post("/chat", json={"message": "hi", "conversation": cid})
    assert r.get_data(as_text=True) == "Hello there"
    saved = client.get("/conversations/" + cid).get_json()
    assert saved["title"] == "hi"
    assert saved["messages"] == [
        {"role": "user", "text": "hi"},
        {"role": "model", "text": "Hello there"},
    ]


def test_chat_rejects_empty_message(client):
    r = client.post("/chat", json={"message": "  "})
    assert r.status_code == 400


def test_chat_unknown_conversation(client):
    r = client.post("/chat", json={"message": "hi", "conversation": "aaaaaaaaaaaa"})
    assert r.status_code == 404


def test_delete_conversation(client):
    cid = client.post("/conversations").get_json()["id"]
    assert client.delete("/conversations/" + cid).status_code == 200
    assert client.get("/conversations/" + cid).status_code == 404


def test_open_when_no_password_set(client):
    assert client.get("/conversations").status_code == 200


def test_password_required_when_set(client, monkeypatch):
    monkeypatch.setenv("NOVA_PASSWORD", "secret")
    assert client.get("/conversations").status_code == 401
    assert client.get("/conversations", headers=basic("wrong")).status_code == 401
    assert client.get("/conversations", headers=basic("secret")).status_code == 200