from types import SimpleNamespace

from app.tool_loop import run_turn


def text_chunk(text):
    part = SimpleNamespace(text=text, function_call=None)
    content = SimpleNamespace(parts=[part])
    return SimpleNamespace(
        candidates=[SimpleNamespace(content=content)], usage_metadata=None
    )


def call_chunk(*names):
    parts = [
        SimpleNamespace(text=None, function_call=SimpleNamespace(name=n, args={}))
        for n in names
    ]
    content = SimpleNamespace(parts=parts)
    return SimpleNamespace(
        candidates=[SimpleNamespace(content=content)], usage_metadata=None
    )


class ScriptedChat:
    """Returns one scripted list of chunks per call to send_message_stream."""

    def __init__(self, *responses):
        self.responses = list(responses)

    def send_message_stream(self, message):
        return iter(self.responses.pop(0))


class FakeRegistry:
    def execute(self, name, args):
        return SimpleNamespace(ok=True, output="done", error=None)


def test_a_turn_without_tools_records_none():
    chat = ScriptedChat([text_chunk("Hello")])
    result = run_turn(chat, "hi", FakeRegistry())
    assert result.reply == "Hello"
    assert result.tools_used == []
    assert result.tool_calls == 0


def test_tool_names_are_recorded_in_order():
    chat = ScriptedChat(
        [call_chunk("search_documents")],
        [call_chunk("calculator", "write_file")],
        [text_chunk("Done")],
    )
    result = run_turn(chat, "go", FakeRegistry())
    assert result.tools_used == ["search_documents", "calculator", "write_file"]
    assert result.tool_calls == 3


def test_calls_past_the_round_limit_are_not_recorded():
    chat = ScriptedChat(
        [call_chunk("calculator")],
        [text_chunk("Answer anyway")],
    )
    result = run_turn(chat, "go", FakeRegistry(), max_rounds=0)
    assert result.hit_round_limit is True
    assert result.tools_used == []
    assert result.tool_calls == 0
    assert result.reply == "Answer anyway"


def test_each_turn_has_its_own_list():
    first = run_turn(ScriptedChat([call_chunk("calculator")], [text_chunk("a")]), "x", FakeRegistry())
    second = run_turn(ScriptedChat([text_chunk("b")]), "y", FakeRegistry())
    assert first.tools_used == ["calculator"]
    assert second.tools_used == []