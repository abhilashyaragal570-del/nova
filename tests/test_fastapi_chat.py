import json
import threading
import time
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from google.genai import errors

from memory.conversation_store import ConversationStore
from web import fastapi_app, server
from web.approvals import ApprovalBroker

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


class FakeSession:
    def __init__(self, streams):
        self.streams = list(streams)

    def send_message_stream(self, message):
        item = self.streams.pop(0)
        if isinstance(item, Exception):
            raise item
        return iter(item)


class Harness:
    """The FastAPI app with a temporary store and a fake chat session."""

    def __init__(self, monkeypatch, tmp_path, streams):
        monkeypatch.setenv("NOVA_PASSWORD", "secret")
        self.store = ConversationStore(
            tmp_path / "conversations", tmp_path / "history.json"
        )
        self.streams = list(streams)
        self.chats = []
        self.logged = []
        self.durations = []
        self.waits = []
        monkeypatch.setattr(server, "store", self.store)
        monkeypatch.setattr(server, "current_prompt", "Original prompt")
        monkeypatch.setattr(server, "new_chat", self.new_chat)
        monkeypatch.setattr(server, "log_turn", self.log_turn)
        self.client = TestClient(fastapi_app.app)
        self.client.auth = AUTH

    def log_turn(
        self, result, source="", duration_seconds=None, approval_wait_seconds=None
    ):
        self.logged.append(source)
        self.durations.append(duration_seconds)
        self.waits.append(approval_wait_seconds)
        return True

    def new_chat(self, messages, prompt):
        self.chats.append({"messages": list(messages), "prompt": prompt})
        return FakeSession([self.streams.pop(0)])

    def new_conversation(self):
        return self.client.post("/conversations").json()["id"]

    def say(self, text, conversation=None):
        body = {"message": text}
        if conversation is not None:
            body["conversation"] = conversation
        res = self.client.post("/chat", json=body)
        return res, res.text


def test_chat_needs_the_password(monkeypatch, tmp_path):
    Harness(monkeypatch, tmp_path, [])
    anon = TestClient(fastapi_app.app)
    res = anon.post("/chat", json={"message": "hi"})
    assert res.status_code == 401
    assert "Basic" in res.headers["www-authenticate"]


@pytest.mark.parametrize(
    "body",
    [{}, {"message": ""}, {"message": "   "}, {"message": None}, {"message": 5}],
)
def test_a_bad_message_is_a_400(monkeypatch, tmp_path, body):
    h = Harness(monkeypatch, tmp_path, [])
    res = h.client.post("/chat", json=body)
    assert res.status_code == 400
    assert res.json() == {"error": "Empty message"}
    assert h.chats == []


def test_a_body_that_is_not_an_object_is_a_400(monkeypatch, tmp_path):
    h = Harness(monkeypatch, tmp_path, [])
    assert h.client.post("/chat", json=[1, 2]).status_code == 400
    res = h.client.post(
        "/chat", content="not json", headers={"Content-Type": "application/json"}
    )
    assert res.status_code == 400
    assert h.client.post("/chat").status_code == 400
    assert h.chats == []


def test_an_unknown_conversation_is_a_404(monkeypatch, tmp_path):
    h = Harness(monkeypatch, tmp_path, [])
    res, _ = h.say("hi", conversation="aaaaaaaaaaaa")
    assert res.status_code == 404
    assert res.json() == {"error": "Conversation not found"}
    assert h.chats == []


def test_a_conversation_that_is_not_text_is_a_404(monkeypatch, tmp_path):
    h = Harness(monkeypatch, tmp_path, [])
    res, _ = h.say("hi", conversation=5)
    assert res.status_code == 404
    assert res.json() == {"error": "Conversation not found"}


def test_the_reply_is_streamed_and_saved(monkeypatch, tmp_path):
    h = Harness(monkeypatch, tmp_path, [[chunk("Hello "), chunk("there")]])
    cid = h.new_conversation()
    res, body = h.say("hi", conversation=cid)
    assert res.status_code == 200
    assert res.headers["content-type"].startswith("text/plain")
    assert body == "Hello there"
    saved = h.client.get("/conversations/" + cid).json()
    assert saved["title"] == "hi"
    assert saved["messages"] == [
        {"role": "user", "text": "hi"},
        {"role": "model", "text": "Hello there"},
    ]


def test_no_conversation_means_the_main_chat(monkeypatch, tmp_path):
    h = Harness(monkeypatch, tmp_path, [[chunk("ok")]])
    _, body = h.say("hi")
    assert body == "ok"
    main = h.client.get("/conversations/main").json()
    assert main["title"] == "Main chat"
    assert len(main["messages"]) == 2


def test_a_long_first_message_gives_a_40_character_title(monkeypatch, tmp_path):
    h = Harness(monkeypatch, tmp_path, [[chunk("ok")]])
    cid = h.new_conversation()
    h.say("x" * 60, conversation=cid)
    assert h.client.get("/conversations/" + cid).json()["title"] == "x" * 40


def test_the_title_is_kept_after_the_first_message(monkeypatch, tmp_path):
    h = Harness(monkeypatch, tmp_path, [[chunk("a")], [chunk("b")]])
    cid = h.new_conversation()
    h.say("first", conversation=cid)
    h.say("second", conversation=cid)
    saved = h.client.get("/conversations/" + cid).json()
    assert saved["title"] == "first"
    assert len(saved["messages"]) == 4


def test_the_token_line_follows_the_reply(monkeypatch, tmp_path):
    h = Harness(monkeypatch, tmp_path, [[chunk("ok", tokens=(3, 4))]])
    _, body = h.say("hi")
    text, _, info = body.partition("\x00")
    assert text == "ok"
    assert json.loads(info) == {"prompt": 3, "reply": 4, "total": 7, "tools": []}


def test_an_api_error_is_reported_and_not_saved(monkeypatch, tmp_path):
    boom = errors.APIError(500, {"error": {"message": "boom"}})
    h = Harness(monkeypatch, tmp_path, [boom])
    cid = h.new_conversation()
    _, body = h.say("hi", conversation=cid)
    assert "Nova couldn't reply: error 500" in body
    assert h.client.get("/conversations/" + cid).json()["messages"] == []


def test_the_chat_gets_the_personality_and_the_saved_messages(monkeypatch, tmp_path):
    h = Harness(monkeypatch, tmp_path, [[chunk("a")], [chunk("b")]])
    h.client.post("/system", json={"prompt": "You are a pirate."})
    cid = h.new_conversation()
    h.say("one", conversation=cid)
    h.say("two", conversation=cid)
    assert h.chats[0]["prompt"] == "You are a pirate."
    assert h.chats[0]["messages"] == []
    assert len(h.chats[1]["messages"]) == 2


def test_the_turn_is_logged_as_web(monkeypatch, tmp_path):
    h = Harness(monkeypatch, tmp_path, [[chunk("a")]])
    h.say("hi")
    assert h.logged == ["web"]


def test_the_turn_time_is_logged(monkeypatch, tmp_path):
    h = Harness(monkeypatch, tmp_path, [[chunk("a")]])
    h.say("hi")
    assert len(h.durations) == 1
    assert isinstance(h.durations[0], float)
    assert h.durations[0] >= 0


def test_the_approval_wait_is_logged_separately(monkeypatch, tmp_path):
    h = Harness(monkeypatch, tmp_path, [])
    broker = ApprovalBroker(timeout=5)
    monkeypatch.setattr(server, "approvals", broker)

    class WaitingSession:
        def send_message_stream(self, message):
            def answer_soon():
                for _ in range(300):
                    pending = broker.list_pending()
                    if pending:
                        time.sleep(0.05)
                        broker.resolve(pending[0]["id"], True)
                        return
                    time.sleep(0.01)

            threading.Thread(target=answer_soon).start()
            # Blocks this worker thread until the other thread answers.
            broker.confirm("write_file", {"path": "a.txt"})
            yield chunk("ok")

    monkeypatch.setattr(server, "new_chat", lambda messages, prompt: WaitingSession())
    _, body = h.say("hi")
    assert body == "ok"
    assert len(h.waits) == 1
    assert h.waits[0] >= 0.04
    # The wait is rounded to 3 decimals and the duration is not, so allow 1 ms.
    assert h.durations[0] + 0.001 >= h.waits[0]


def test_chat_is_listed_in_docs(monkeypatch, tmp_path):
    h = Harness(monkeypatch, tmp_path, [])
    paths = h.client.get("/openapi.json").json()["paths"]
    assert "/chat" in paths