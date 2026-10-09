from types import SimpleNamespace

import pytest
from google.genai import errors

from agents.auto import Session, auto_loop, choose_agent
from agents.definitions import AGENTS, AgentSpec, get_agent
from tools.registry import ToolRegistry


def chunk(text):
    part = SimpleNamespace(text=text, function_call=None)
    candidate = SimpleNamespace(content=SimpleNamespace(parts=[part]))
    return SimpleNamespace(candidates=[candidate], usage_metadata=None)


class FakeChat:
    def __init__(self, streams=()):
        self.streams = list(streams)
        self.sent = []

    def send_message_stream(self, message):
        self.sent.append(message)
        item = self.streams.pop(0)
        if isinstance(item, Exception):
            raise item
        return iter(item)


def run(inputs, chats):
    lines = iter(inputs)

    def read(prompt):
        try:
            return next(lines)
        except StopIteration:
            raise EOFError

    created = []

    def make(name):
        created.append(name)
        if name in AGENTS:
            spec = get_agent(name)
        else:
            spec = AgentSpec(name, "d", "p", frozenset())
        return Session(spec, chats[name], ToolRegistry(), [])

    auto_loop(make, read=read, write=lambda t: None)
    return created


# choose_agent on its own


def test_pinned_agent_always_wins():
    assert choose_agent("list files", "notes", "researcher") == "notes"


def test_a_clear_router_match_beats_the_follow_up_rule():
    assert choose_agent("list files", None, "researcher") == "files"


@pytest.mark.parametrize("text", ["and tomorrow?", "what about Mumbai?", "why?"])
def test_short_unmatched_message_stays_with_the_last_agent(text):
    assert choose_agent(text, None, "researcher") == "researcher"


def test_long_unmatched_message_goes_to_nova():
    text = "please tell me a long story about dragons"
    assert choose_agent(text, None, "researcher") == "nova"


def test_the_word_limit_is_four():
    assert choose_agent("and what about Delhi", None, "researcher") == "researcher"
    assert choose_agent("and what about Delhi then", None, "researcher") == "nova"


def test_no_previous_agent_means_nova():
    assert choose_agent("and tomorrow?", None, None) == "nova"


def test_nova_is_not_sticky():
    assert choose_agent("and you?", None, "nova") == "nova"


# the loop


def test_follow_ups_continue_with_the_same_agent():
    chats = {
        "researcher": FakeChat([[chunk("a")], [chunk("b")], [chunk("c")]])
    }
    created = run(
        ["weather in Bengaluru", "and tomorrow?", "what about Mumbai?", "exit"], chats
    )
    assert chats["researcher"].sent == [
        "weather in Bengaluru",
        "and tomorrow?",
        "what about Mumbai?",
    ]
    assert created == ["researcher"]


def test_nova_answers_do_not_make_later_messages_follow_ups():
    chats = {"nova": FakeChat([[chunk("a")], [chunk("b")]])}
    created = run(["please tell me a short story", "and then?", "exit"], chats)
    assert chats["nova"].sent == ["please tell me a short story", "and then?"]
    assert created == ["nova"]


def test_a_new_clear_match_switches_agent_mid_conversation():
    chats = {
        "researcher": FakeChat([[chunk("r")]]),
        "files": FakeChat([[chunk("f")]]),
    }
    run(["weather in Bengaluru", "list files", "exit"], chats)
    assert chats["files"].sent == ["list files"]


def test_a_failed_turn_does_not_count_as_the_previous_agent():
    boom = errors.APIError(500, {"error": {"message": "boom"}})
    chats = {
        "researcher": FakeChat([boom]),
        "nova": FakeChat([[chunk("n")]]),
    }
    run(["weather in Bengaluru", "and tomorrow?", "exit"], chats)
    assert chats["nova"].sent == ["and tomorrow?"]