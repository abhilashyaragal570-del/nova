from types import SimpleNamespace

import pytest

from agents.auto import Session, auto_loop, choose_agent
from agents.definitions import AGENTS, AgentSpec, get_agent
from agents.smart_router import build_prompt, classify_with_model, make_classifier
from tools.registry import ToolRegistry


class FakeModels:
    def __init__(self, reply=None, error=None):
        self.reply = reply
        self.error = error
        self.kwargs = None

    def generate_content(self, **kwargs):
        self.kwargs = kwargs
        if self.error:
            raise self.error
        return SimpleNamespace(text=self.reply)


class FakeClient:
    def __init__(self, **kwargs):
        self.models = FakeModels(**kwargs)


# classify_with_model


@pytest.mark.parametrize(
    "reply, expected",
    [
        ("notes", "notes"),
        ("Notes", "notes"),
        ("notes.", "notes"),
        ("  researcher\n", "researcher"),
        ("`files`", "files"),
        ('"files"', "files"),
    ],
)
def test_a_clean_reply_names_the_agent(reply, expected):
    assert classify_with_model(FakeClient(reply=reply), "m", "q") == expected


@pytest.mark.parametrize(
    "reply",
    ["none", "nova", "I think notes", "notes or files", "", "banana", None],
)
def test_anything_else_is_none(reply):
    assert classify_with_model(FakeClient(reply=reply), "m", "q") is None


def test_a_model_error_is_none():
    client = FakeClient(error=RuntimeError("boom"))
    assert classify_with_model(client, "m", "q") is None


def test_the_prompt_has_the_message_the_agents_and_a_data_warning():
    client = FakeClient(reply="notes")
    classify_with_model(client, "test-model", "my question")
    kwargs = client.models.kwargs
    assert kwargs["model"] == "test-model"
    assert "my question" in kwargs["contents"]
    for name in AGENTS:
        assert name in kwargs["contents"]
    assert "untrusted" in kwargs["contents"].lower()


def test_a_very_long_message_is_cut():
    prompt = build_prompt("Q" * 5000)
    assert prompt.count("Q") == 500

def test_make_classifier_wraps_the_client():
    classify = make_classifier(FakeClient(reply="files"), "m")
    assert classify("anything") == "files"


# choose_agent with a classifier

QUESTION = "please tell me about the budget plan"


def spy(answer):
    calls = []

    def classify(text):
        calls.append(text)
        if isinstance(answer, Exception):
            raise answer
        return answer

    return classify, calls


def test_the_classifier_is_used_when_no_rule_matches():
    classify, calls = spy("notes")
    assert choose_agent(QUESTION, None, None, classify) == "notes"
    assert calls == [QUESTION]


def test_the_classifier_is_not_asked_when_pinned():
    classify, calls = spy("notes")
    assert choose_agent(QUESTION, "files", None, classify) == "files"
    assert calls == []


def test_the_classifier_cannot_move_a_write_request():
    classify, calls = spy("files")
    assert choose_agent("create a file called a.txt", None, None, classify) == "nova"
    assert calls == []


def test_the_classifier_is_not_asked_when_a_rule_matches():
    classify, calls = spy("notes")
    assert choose_agent("list files", None, None, classify) == "files"
    assert calls == []


def test_the_classifier_is_not_asked_for_a_short_follow_up():
    classify, calls = spy("notes")
    assert choose_agent("and tomorrow?", None, "researcher", classify) == "researcher"
    assert calls == []


def test_a_classifier_error_falls_back_to_nova():
    classify, _ = spy(RuntimeError("boom"))
    assert choose_agent(QUESTION, None, None, classify) == "nova"


@pytest.mark.parametrize("answer", [None, "banana", "nova"])
def test_a_useless_answer_falls_back_to_nova(answer):
    classify, _ = spy(answer)
    assert choose_agent(QUESTION, None, None, classify) == "nova"


def test_without_a_classifier_nothing_changes():
    assert choose_agent(QUESTION, None, None) == "nova"


# the loop


def test_loop_uses_the_classifier_and_the_follow_up_sticks():
    def chunk(text):
        part = SimpleNamespace(text=text, function_call=None)
        candidate = SimpleNamespace(content=SimpleNamespace(parts=[part]))
        return SimpleNamespace(candidates=[candidate], usage_metadata=None)

    class FakeChat:
        def __init__(self):
            self.streams = [[chunk("a")], [chunk("b")]]
            self.sent = []

        def send_message_stream(self, message):
            self.sent.append(message)
            return iter(self.streams.pop(0))

    chat = FakeChat()
    created = []

    def make(name):
        created.append(name)
        return Session(get_agent(name), chat, ToolRegistry(), [])

    lines = iter([QUESTION, "and the second one?", "exit"])
    auto_loop(
        make,
        read=lambda prompt: next(lines),
        write=lambda t: None,
        classify=lambda text: "notes",
    )
    assert chat.sent == [QUESTION, "and the second one?"]
    assert created == ["notes"]