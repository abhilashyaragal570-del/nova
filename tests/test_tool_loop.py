from types import SimpleNamespace

from google.genai import types

from app.tool_loop import run_turn
from tools.calculator import CalculatorTool
from tools.registry import ToolRegistry


class FakeChat:
    """Plays back scripted rounds of chunks; records what Nova sends."""

    def __init__(self, rounds):
        self.rounds = rounds
        self.sent = []

    def send_message_stream(self, message):
        self.sent.append(message)
        i = min(len(self.sent) - 1, len(self.rounds) - 1)
        return iter(self.rounds[i])


def usage(total=15):
    return SimpleNamespace(
        prompt_token_count=10, candidates_token_count=total - 10, total_token_count=total
    )


def text_chunk(text, with_usage=True):
    return SimpleNamespace(
        text=text,
        function_calls=None,
        usage_metadata=usage() if with_usage else None,
    )


def call_chunk(name="calculator", args=None):
    call = types.FunctionCall(name=name, args=args or {"expression": "458 * 923"})
    return SimpleNamespace(text=None, function_calls=[call], usage_metadata=usage())


def make_registry():
    reg = ToolRegistry()
    reg.register(CalculatorTool())
    return reg


def test_plain_answer_without_tools():
    chat = FakeChat([[text_chunk("Hello there")]])
    result = run_turn(chat, "hi", make_registry())
    assert result.reply == "Hello there"
    assert result.tool_calls == 0 and not result.hit_round_limit
    assert chat.sent == ["hi"]


def test_tool_call_then_final_answer():
    chat = FakeChat([[call_chunk()], [text_chunk("The answer is 422,734.")]])
    result = run_turn(chat, "What is 458 * 923?", make_registry())
    assert result.reply == "The answer is 422,734."
    assert result.tool_calls == 1
    sent_back = chat.sent[1][0].function_response
    assert sent_back.name == "calculator"
    assert sent_back.response == {"result": 422734}


def test_unknown_tool_returns_error_to_model():
    chat = FakeChat([[call_chunk(name="nope", args={})], [text_chunk("Sorry.")]])
    result = run_turn(chat, "do it", make_registry())
    assert result.reply == "Sorry."
    assert "Unknown tool" in chat.sent[1][0].function_response.response["error"]


def test_round_limit_stops_runaway_loop():
    chat = FakeChat([[call_chunk()]])  # model asks for a tool forever
    result = run_turn(chat, "loop", make_registry(), max_rounds=2)
    assert result.hit_round_limit
    assert len(chat.sent) == 4
    error = chat.sent[3][0].function_response.response["error"]
    assert "limit" in error.lower()


def test_tokens_accumulate_across_rounds():
    chat = FakeChat([[call_chunk()], [text_chunk("done")]])
    result = run_turn(chat, "x", make_registry())
    assert result.total_tokens == 30
    assert result.prompt_tokens == 20


def test_on_text_receives_streamed_chunks():
    chat = FakeChat([[text_chunk("Hel", False), text_chunk("lo")]])
    seen = []
    run_turn(chat, "hi", make_registry(), on_text=seen.append)
    assert seen == ["Hel", "lo"]