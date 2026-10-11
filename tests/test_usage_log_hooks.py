import json
from types import SimpleNamespace

from agents.auto import Session, auto_loop
from agents.definitions import AgentSpec
from agents.runner import chat_loop
from app.usage_log import get_log_path


def text_chunk(text):
    part = SimpleNamespace(text=text, function_call=None)
    content = SimpleNamespace(parts=[part])
    return SimpleNamespace(
        candidates=[SimpleNamespace(content=content)], usage_metadata=None
    )


def call_chunk(name):
    part = SimpleNamespace(text=None, function_call=SimpleNamespace(name=name, args={}))
    content = SimpleNamespace(parts=[part])
    return SimpleNamespace(
        candidates=[SimpleNamespace(content=content)], usage_metadata=None
    )


class ScriptedChat:
    def __init__(self, *responses):
        self.responses = list(responses)

    def send_message_stream(self, message):
        return iter(self.responses.pop(0))


class FakeRegistry:
    def execute(self, name, args):
        return SimpleNamespace(ok=True, output="done", error=None)


def make_spec(name):
    return AgentSpec(
        name=name, description="test agent", system_prompt="be brief", tools=frozenset()
    )


def feed(*lines):
    it = iter(lines)
    return lambda prompt: next(it)


def read_entries():
    text = get_log_path().read_text(encoding="utf-8")
    return [json.loads(line) for line in text.splitlines()]


def test_agent_terminal_chat_logs_each_turn():
    chat = ScriptedChat([call_chunk("calculator")], [text_chunk("42")])
    chat_loop(
        chat,
        FakeRegistry(),
        make_spec("math"),
        read=feed("what is 6*7", "exit"),
        write=lambda text: None,
    )
    entries = read_entries()
    assert len(entries) == 1
    assert entries[0]["source"] == "terminal-agent:math"
    assert entries[0]["tools"] == ["calculator"]


def test_auto_chat_logs_each_turn():
    def make_session(name):
        return Session(
            spec=make_spec(name),
            chat=ScriptedChat([call_chunk("calculator")], [text_chunk("42")]),
            registry=FakeRegistry(),
            messages=[],
        )

    auto_loop(make_session, read=feed("what is 6*7", "exit"), write=lambda text: None)
    entries = read_entries()
    assert len(entries) == 1
    assert entries[0]["source"].startswith("auto:")
    assert entries[0]["tools"] == ["calculator"]