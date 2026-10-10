import base64
import json
from types import SimpleNamespace

import pytest
from flask import Flask
from google.genai import errors

from agents.definitions import AGENTS
from agents.history import load_messages
from memory.conversation_store import ConversationStore
from tools.registry import ToolRegistry
from web.agents_api import register_agent_routes


def chunk(text, tokens=None):
    part = SimpleNamespace(text=text, function_call=None)
    candidate = SimpleNamespace(content=SimpleNamespace(parts=[part]))
    usage = None
    if tokens:
        usage = SimpleNamespace(
            prompt_token_count=tokens[0],
            candidates_token_count=tokens[1],
            total_token_count=sum(tokens),
        )
    return SimpleNamespace(candidates=[candidate], usage_metadata=usage)


class FakeChat:
    def __init__(self, streams):
        self.streams = list(streams)

    def send_message_stream(self, message):
        item = self.streams.pop(0)
        if isinstance(item, Exception):
            raise item
        return iter(item)


class Harness:
    """A throwaway Flask app with the agent routes and a fake chat factory."""

    def __init__(self, tmp_path, streams):
        self.store = ConversationStore(
            conv_dir=tmp_path / "conversations",
            history_file=tmp_path / "history.json",
        )
        self.streams = list(streams)
        self.calls = []
        self.source = ToolRegistry()
        self.tmp_path = tmp_path
        app = Flask(__name__)
        register_agent_routes(
            app, self.source, self.store, "client", "model", chat_factory=self.factory
        )
        self.client = app.test_client()

    def factory(self, client, model, spec, source, contents):
        self.calls.append(
            {"spec": spec.name, "source": source, "contents": list(contents)}
        )
        return FakeChat([self.streams.pop(0)]), ToolRegistry()

    def say(self, name, text):
        resp = self.client.post(f"/api/agents/{name}/chat", json={"message": text})
        return resp, resp.get_data(as_text=True)


def test_agents_are_listed_without_nova(tmp_path):
    h = Harness(tmp_path, [])
    data = h.client.get("/api/agents").get_json()
    assert {a["name"] for a in data} == set(AGENTS)
    assert "nova" not in {a["name"] for a in data}
    notes = next(a for a in data if a["name"] == "notes")
    assert notes["tools"] == ["search_documents"]


def test_unknown_agent_is_a_404(tmp_path):
    h = Harness(tmp_path, [])
    resp, _ = h.say("banana", "hi")
    assert resp.status_code == 404
    assert h.client.get("/api/agents/banana/history").status_code == 404
    assert h.client.delete("/api/agents/banana/history").status_code == 404


@pytest.mark.parametrize(
    "body", [{}, {"message": ""}, {"message": "   "}, {"message": 5}]
)
def test_a_bad_message_is_a_400(tmp_path, body):
    h = Harness(tmp_path, [])
    resp = h.client.post("/api/agents/notes/chat", json=body)
    assert resp.status_code == 400
    assert h.calls == []


def test_the_reply_is_streamed_and_saved(tmp_path):
    h = Harness(tmp_path, [[chunk("Hello "), chunk("there")]])
    resp, body = h.say("notes", "hi")
    assert resp.status_code == 200
    assert body == "Hello there"
    spec = SimpleNamespace(name="notes")
    assert load_messages(h.store, spec) == [
        {"role": "user", "text": "hi"},
        {"role": "model", "text": "Hello there"},
    ]


def test_the_token_line_follows_the_reply(tmp_path):
    h = Harness(tmp_path, [[chunk("ok", tokens=(3, 4))]])
    _, body = h.say("notes", "hi")
    text, _, info = body.partition("\x00")
    assert text == "ok"
    assert json.loads(info) == {"prompt": 3, "reply": 4, "total": 7}


def test_the_factory_gets_the_agent_and_the_source_registry(tmp_path):
    h = Harness(tmp_path, [[chunk("a")]])
    h.say("files", "list files")
    assert h.calls[0]["spec"] == "files"
    assert h.calls[0]["source"] is h.source


def test_a_second_message_resumes_the_saved_conversation(tmp_path):
    h = Harness(tmp_path, [[chunk("a")], [chunk("b")]])
    h.say("notes", "one")
    h.say("notes", "two")
    assert h.calls[0]["contents"] == []
    assert len(h.calls[1]["contents"]) == 2


def test_an_api_error_is_reported_and_not_saved(tmp_path):
    boom = errors.APIError(500, {"error": {"message": "boom"}})
    h = Harness(tmp_path, [boom])
    _, body = h.say("notes", "hi")
    assert "error 500" in body
    assert h.client.get("/api/agents/notes/history").get_json()["messages"] == []


def test_history_can_be_read_and_cleared(tmp_path):
    h = Harness(tmp_path, [[chunk("a")]])
    h.say("notes", "hi")
    messages = h.client.get("/api/agents/notes/history").get_json()["messages"]
    assert len(messages) == 2
    assert h.client.delete("/api/agents/notes/history").get_json() == {"ok": True}
    assert h.client.get("/api/agents/notes/history").get_json()["messages"] == []


def test_agent_chats_never_touch_the_main_history(tmp_path):
    h = Harness(tmp_path, [[chunk("a")]])
    h.say("notes", "hi")
    assert not (tmp_path / "history.json").exists()


def test_the_real_server_protects_the_agent_routes(monkeypatch):
    monkeypatch.setenv("NOVA_PASSWORD", "pw")
    from web import server

    client = server.app.test_client()
    assert client.get("/api/agents").status_code == 401
    token = base64.b64encode(b"user:pw").decode()
    resp = client.get("/api/agents", headers={"Authorization": f"Basic {token}"})
    assert resp.status_code == 200
    assert {a["name"] for a in resp.get_json()} == set(AGENTS)