from types import SimpleNamespace

from google.genai import errors

from agents.definitions import get_agent
from agents.runner import chat_loop
from tools.registry import ToolRegistry


def chunk(text, tokens=(1, 1)):
    part = SimpleNamespace(text=text, function_call=None)
    candidate = SimpleNamespace(content=SimpleNamespace(parts=[part]))
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


def run(chat, inputs, messages=None, save=None):
    lines = iter(inputs)

    def read(prompt):
        try:
            return next(lines)
        except StopIteration:
            raise EOFError

    out = []
    chat_loop(
        chat,
        ToolRegistry(),
        get_agent("notes"),
        read=read,
        write=out.append,
        messages=messages,
        save=save,
    )
    return "".join(out)


def test_each_answered_turn_is_saved():
    saved = []
    chat = FakeChat([[chunk("Hello")]])
    run(chat, ["hi", "exit"], messages=[], save=lambda m: saved.append(list(m)))
    assert saved == [
        [{"role": "user", "text": "hi"}, {"role": "model", "text": "Hello"}]
    ]


def test_a_failed_turn_is_not_saved():
    saved = []
    boom = errors.APIError(500, {"error": {"message": "boom"}})
    chat = FakeChat([boom])
    run(chat, ["hi", "exit"], messages=[], save=lambda m: saved.append(list(m)))
    assert saved == []


def test_a_save_failure_does_not_end_the_session():
    def broken(messages):
        raise OSError("disk full")

    chat = FakeChat([[chunk("a")], [chunk("b")]])
    output = run(chat, ["one", "two", "exit"], messages=[], save=broken)
    assert output.count("couldn't save") == 2


def test_earlier_messages_are_announced_and_extended():
    saved = []
    earlier = [{"role": "user", "text": "old q"}, {"role": "model", "text": "old a"}]
    chat = FakeChat([[chunk("new a")]])
    output = run(chat, ["new q", "exit"], messages=earlier, save=lambda m: saved.append(list(m)))
    assert "Loaded 2 earlier messages" in output
    assert len(saved[0]) == 4
    assert saved[0][-1] == {"role": "model", "text": "new a"}