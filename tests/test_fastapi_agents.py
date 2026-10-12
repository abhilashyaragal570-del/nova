import json
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from google.genai import errors

from agents.definitions import AGENTS, AgentError
from agents.history import load_messages
from memory.conversation_store import ConversationStore
from tools.registry import ToolRegistry
from web import fastapi_app, server

AUTH = ("nova", "secret")


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
    """The FastAPI app with a temporary store and a fake chat factory."""

    def __init__(self, monkeypatch, tmp_path, streams):
        monkeypatch.setenv("NOVA_PASSWORD", "secret")
        self.store = ConversationStore(
            conv_dir=tmp_path / "conversations",
            history_file=tmp_path / "history.json",
        )
        self.streams = list(streams)
        self.calls = []
        self.source = ToolRegistry()
        self.tmp_path = tmp_path
        monkeypatch.setattr(server, "store", self.store)
        monkeypatch.setattr(server, "web_registry", self.source)
        monkeypatch.setattr(server, "llm_client", "client")
        monkeypatch.setattr(server, "MODEL_NAME", "model")
        monkeypatch.setattr(fastapi_app, "chat_factory", self.factory)
        monkeypatch.setattr(fastapi_app, "log_turn", lambda *a, **k: None)
        self.client = TestClient(fastapi_app.app)
        self.client.auth = AUTH

    def factory(self, client, model, spec, source, contents):
        self.calls.append(
            {
                "spec": spec.name,
                "client": client,
                "model": model,
                "source": source,
                "contents": list(contents),
            }
        )
        return FakeChat([self.streams.pop(0)]), ToolRegistry()

    def say(self, name, text):
        res = self.client.post(f"/api/agents/{name}/chat", json={"message": text})
        return res, res.text


def test_routes_require_the_password(monkeypatch, tmp_path):
    Harness(monkeypatch, tmp_path, [])
    anon = TestClient(fastapi_app.app)
    assert anon.get("/api/agents").status_code == 401
    assert anon.get("/api/agents/notes/history").status_code == 401
    assert anon.delete("/api/agents/notes/history").status_code == 401
    assert anon.post("/api/agents/notes/chat", json={"message": "hi"}).status_code == 401


def test_agents_are_listed_without_nova(monkeypatch, tmp_path):
    h = Harness(monkeypatch, tmp_path, [])
    data = h.client.get("/api/agents").json()
    assert {a["name"] for a in data} == set(AGENTS)
    assert "nova" not in {a["name"] for a in data}
    notes = next(a for a in data if a["name"] == "notes")
    assert notes["tools"] == ["search_documents"]


def test_unknown_agent_is_a_404(monkeypatch, tmp_path):
    h = Harness(monkeypatch, tmp_path, [])
    res, _ = h.say("banana", "hi")
    assert res.status_code == 404
    assert res.json() == {"error": "Unknown agent"}
    assert h.client.get("/api/agents/banana/history").status_code == 404
    assert h.client.delete("/api/agents/banana/history").status_code == 404


@pytest.mark.parametrize(
    "body", [{}, {"message": ""}, {"message": "   "}, {"message": 5}]
)
def test_a_bad_message_is_a_400(monkeypatch, tmp_path, body):
    h = Harness(monkeypatch, tmp_path, [])
    res = h.client.post("/api/agents/notes/chat", json=body)
    assert res.status_code == 400
    assert res.json() == {"error": "Empty message"}
    assert h.calls == []


def test_a_body_that_is_not_an_object_is_a_400(monkeypatch, tmp_path):
    h = Harness(monkeypatch, tmp_path, [])
    res = h.client.post("/api/agents/notes/chat", json=[1, 2])
    assert res.status_code == 400
    res = h.client.post(
        "/api/agents/notes/chat",
        content="not json",
        headers={"Content-Type": "application/json"},
    )
    assert res.status_code == 400
    assert h.client.post("/api/agents/notes/chat").status_code == 400
    assert h.calls == []


def test_the_reply_is_streamed_and_saved(monkeypatch, tmp_path):
    h = Harness(monkeypatch, tmp_path, [[chunk("Hello "), chunk("there")]])
    res, body = h.say("notes", "hi")
    assert res.status_code == 200
    assert res.headers["content-type"].startswith("text/plain")
    assert body == "Hello there"
    spec = SimpleNamespace(name="notes")
    assert load_messages(h.store, spec) == [
        {"role": "user", "text": "hi"},
        {"role": "model", "text": "Hello there"},
    ]


def test_the_token_line_follows_the_reply(monkeypatch, tmp_path):
    h = Harness(monkeypatch, tmp_path, [[chunk("ok", tokens=(3, 4))]])
    _, body = h.say("notes", "hi")
    text, _, info = body.partition("\x00")
    assert text == "ok"
    assert json.loads(info) == {"prompt": 3, "reply": 4, "total": 7}


def test_the_factory_gets_the_agent_and_the_source_registry(monkeypatch, tmp_path):
    h = Harness(monkeypatch, tmp_path, [[chunk("a")]])
    h.say("files", "list files")
    call = h.calls[0]
    assert call["spec"] == "files"
    assert call["source"] is h.source
    assert call["client"] == "client"
    assert call["model"] == "model"


def test_a_second_message_resumes_the_saved_conversation(monkeypatch, tmp_path):
    h = Harness(monkeypatch, tmp_path, [[chunk("a")], [chunk("b")]])
    h.say("notes", "one")
    h.say("notes", "two")
    assert h.calls[0]["contents"] == []
    assert len(h.calls[1]["contents"]) == 2


def test_an_api_error_is_reported_and_not_saved(monkeypatch, tmp_path):
    boom = errors.APIError(500, {"error": {"message": "boom"}})
    h = Harness(monkeypatch, tmp_path, [boom])
    _, body = h.say("notes", "hi")
    assert "error 500" in body
    assert h.client.get("/api/agents/notes/history").json()["messages"] == []


def test_history_can_be_read_and_cleared(monkeypatch, tmp_path):
    h = Harness(monkeypatch, tmp_path, [[chunk("a")]])
    h.say("notes", "hi")
    messages = h.client.get("/api/agents/notes/history").json()["messages"]
    assert len(messages) == 2
    assert h.client.delete("/api/agents/notes/history").json() == {"ok": True}
    assert h.client.get("/api/agents/notes/history").json()["messages"] == []


def test_agent_chats_never_touch_the_main_history(monkeypatch, tmp_path):
    h = Harness(monkeypatch, tmp_path, [[chunk("a")]])
    h.say("notes", "hi")
    assert not (tmp_path / "history.json").exists()


def test_a_factory_failure_is_a_500(monkeypatch, tmp_path):
    h = Harness(monkeypatch, tmp_path, [])

    def broken(client, model, spec, source, contents):
        raise AgentError("no tools")

    monkeypatch.setattr(fastapi_app, "chat_factory", broken)
    res, _ = h.say("notes", "hi")
    assert res.status_code == 500
    assert res.json() == {"error": "no tools"}


def test_the_agent_routes_are_listed_in_docs(monkeypatch, tmp_path):
    h = Harness(monkeypatch, tmp_path, [])
    paths = h.client.get("/openapi.json").json()["paths"]
    for path in (
        "/api/agents",
        "/api/agents/{name}/history",
        "/api/agents/{name}/chat",
    ):
        assert path in paths