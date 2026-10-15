import json
from types import SimpleNamespace

from fastapi.testclient import TestClient

from memory.conversation_store import ConversationStore
from web import fastapi_app, server

AUTH = ("nova", "secret")


def text_chunk(text, tokens=None):
    part = SimpleNamespace(text=text, function_call=None)
    usage = None
    if tokens:
        usage = SimpleNamespace(
            prompt_token_count=tokens[0],
            candidates_token_count=tokens[1],
            total_token_count=sum(tokens),
        )
    candidate = SimpleNamespace(content=SimpleNamespace(parts=[part]))
    return SimpleNamespace(candidates=[candidate], usage_metadata=usage)


def call_chunk(name):
    call = SimpleNamespace(name=name, args={})
    part = SimpleNamespace(text=None, function_call=call)
    candidate = SimpleNamespace(content=SimpleNamespace(parts=[part]))
    return SimpleNamespace(candidates=[candidate], usage_metadata=None)


class FakeSession:
    def __init__(self, streams):
        self.streams = list(streams)

    def send_message_stream(self, message):
        return iter(self.streams.pop(0))


class FakeRegistry:
    def execute(self, name, args):
        return SimpleNamespace(ok=True, output="4", error=None)


def make_client(monkeypatch, tmp_path, streams):
    monkeypatch.setenv("NOVA_PASSWORD", "secret")
    store = ConversationStore(tmp_path / "conversations", tmp_path / "history.json")
    session = FakeSession(streams)
    monkeypatch.setattr(server, "store", store)
    monkeypatch.setattr(server, "current_prompt", "Original prompt")
    monkeypatch.setattr(server, "new_chat", lambda messages, prompt: session)
    monkeypatch.setattr(server, "web_registry", FakeRegistry())
    monkeypatch.setattr(server, "log_turn", lambda *args, **kwargs: True)
    client = TestClient(fastapi_app.app)
    client.auth = AUTH
    return client


def say(client, text):
    cid = client.post("/conversations").json()["id"]
    response = client.post("/chat", json={"message": text, "conversation": cid})
    assert response.status_code == 200
    return response.text


def test_the_trailer_lists_the_tools_that_ran(monkeypatch, tmp_path):
    streams = [[call_chunk("calculator")], [text_chunk("4", tokens=(3, 4))]]
    client = make_client(monkeypatch, tmp_path, streams)
    body = say(client, "What is 2 + 2?")
    text, _, info = body.partition("\x00")
    assert text == "4"
    assert json.loads(info) == {
        "prompt": 3,
        "reply": 4,
        "total": 7,
        "tools": ["calculator"],
    }


def test_the_trailer_is_sent_when_tools_ran_without_token_counts(monkeypatch, tmp_path):
    streams = [[call_chunk("list_files")], [text_chunk("done")]]
    client = make_client(monkeypatch, tmp_path, streams)
    body = say(client, "List my files")
    text, _, info = body.partition("\x00")
    assert text == "done"
    assert json.loads(info)["tools"] == ["list_files"]