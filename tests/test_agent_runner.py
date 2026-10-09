from types import SimpleNamespace

from google.genai import errors

from agents.definitions import get_agent
from agents.runner import chat_loop
from tools.base import Tool, ToolResult
from tools.registry import ToolRegistry


def chunk(text=None, call=None, tokens=None):
    part = SimpleNamespace(text=text, function_call=call)
    candidate = SimpleNamespace(content=SimpleNamespace(parts=[part]))
    usage = None
    if tokens:
        usage = SimpleNamespace(
            prompt_token_count=tokens[0],
            candidates_token_count=tokens[1],
            total_token_count=tokens[0] + tokens[1],
        )
    return SimpleNamespace(candidates=[candidate], usage_metadata=usage)


class FakeChat:
    """Each send_message_stream call plays back the next scripted stream."""

    def __init__(self, streams):
        self.streams = list(streams)
        self.sent = []

    def send_message_stream(self, message):
        self.sent.append(message)
        item = self.streams.pop(0)
        if isinstance(item, Exception):
            raise item
        return iter(item)


class FakeTool(Tool):
    def __init__(self, name):
        self.name = name
        self.description = "fake"

    def run(self, **kwargs):
        return ToolResult.success("ok")


def run(chat, inputs, registry=None):
    lines = iter(inputs)

    def read(prompt):
        try:
            return next(lines)
        except StopIteration:
            raise EOFError

    out = []
    total = chat_loop(
        chat, registry or ToolRegistry(), get_agent("notes"), read=read, write=out.append
    )
    return total, "".join(out)


def test_reply_is_streamed_and_tokens_are_counted():
    chat = FakeChat([[chunk("Hello "), chunk("there", tokens=(10, 5))]])
    total, output = run(chat, ["hi", "exit"])
    assert "Hello there" in output
    assert "[tokens: prompt 10, reply 5, total 15]" in output
    assert total == 15


def test_tokens_add_up_across_turns():
    chat = FakeChat([[chunk("a", tokens=(1, 1))], [chunk("b", tokens=(2, 3))]])
    total, output = run(chat, ["one", "two", "exit"])
    assert total == 7
    assert "session total: 7 tokens" in output


def test_empty_input_is_skipped():
    chat = FakeChat([])
    run(chat, ["", "   ", "exit"])
    assert chat.sent == []


def test_eof_ends_the_session_cleanly():
    chat = FakeChat([])
    _, output = run(chat, [])
    assert "Goodbye" in output


def test_tool_calls_run_and_are_reported():
    call = SimpleNamespace(name="search_documents", args={})
    chat = FakeChat([[chunk(call=call)], [chunk("done", tokens=(4, 2))]])
    registry = ToolRegistry()
    registry.register(FakeTool("search_documents"))
    _, output = run(chat, ["find it", "exit"], registry)
    assert "done" in output
    assert "[used 1 tool call(s)]" in output
    assert len(chat.sent) == 2


def test_api_error_does_not_end_the_session():
    boom = errors.APIError(500, {"error": {"message": "boom"}})
    chat = FakeChat([boom, [chunk("recovered", tokens=(1, 1))]])
    _, output = run(chat, ["first", "second", "exit"])
    assert "error 500" in output
    assert "recovered" in output