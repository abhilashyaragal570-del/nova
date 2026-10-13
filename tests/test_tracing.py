from types import SimpleNamespace

import pytest

pytest.importorskip("opentelemetry.sdk.trace")
from opentelemetry.sdk.trace.export.in_memory_span_exporter import (  # noqa: E402
    InMemorySpanExporter,
)

from app import tracing  # noqa: E402
from app.tool_loop import run_turn  # noqa: E402


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
    call = SimpleNamespace(name=name, args={"expression": "2+2"})
    part = SimpleNamespace(text=None, function_call=call)
    candidate = SimpleNamespace(content=SimpleNamespace(parts=[part]))
    return SimpleNamespace(candidates=[candidate], usage_metadata=None)


class FakeSession:
    def __init__(self, streams):
        self.streams = list(streams)

    def send_message_stream(self, message):
        return iter(self.streams.pop(0))


class FakeRegistry:
    def execute(self, name, arguments):
        return SimpleNamespace(ok=True, output="4", error=None)


@pytest.fixture
def exporter():
    memory = InMemorySpanExporter()
    tracing.reset()
    assert tracing.setup_tracing(exporter=memory) is True
    yield memory
    tracing.reset()


def spans_named(exporter, name):
    return [s for s in exporter.get_finished_spans() if s.name == name]


def test_nothing_is_recorded_when_tracing_is_off(monkeypatch):
    monkeypatch.delenv("NOVA_TRACING", raising=False)
    tracing.reset()
    assert tracing.setup_tracing() is False
    result = run_turn(FakeSession([[text_chunk("hello")]]), "hi", FakeRegistry())
    assert result.reply == "hello"
    tracing.reset()


def test_a_turn_has_a_turn_span_and_a_model_span(exporter):
    run_turn(FakeSession([[text_chunk("hello")]]), "hi", FakeRegistry())
    assert len(spans_named(exporter, "nova.turn")) == 1
    assert len(spans_named(exporter, "nova.model_call")) == 1


def test_the_turn_span_has_counts_and_tokens(exporter):
    run_turn(
        FakeSession([[text_chunk("ok", tokens=(3, 4))]]), "hi", FakeRegistry()
    )
    turn = spans_named(exporter, "nova.turn")[0]
    assert turn.attributes["nova.total_tokens"] == 7
    assert turn.attributes["nova.tool_calls"] == 0
    assert turn.attributes["nova.hit_round_limit"] is False


def test_a_tool_call_is_a_span_inside_the_turn(exporter):
    session = FakeSession([[call_chunk("calculator")], [text_chunk("4")]])
    result = run_turn(session, "what is 2+2", FakeRegistry())
    assert result.tool_calls == 1
    turn = spans_named(exporter, "nova.turn")[0]
    tool = spans_named(exporter, "nova.tool")[0]
    assert tool.attributes["nova.tool_name"] == "calculator"
    assert tool.attributes["nova.tool_ok"] is True
    assert tool.parent.span_id == turn.context.span_id
    assert len(spans_named(exporter, "nova.model_call")) == 2


def test_message_text_is_never_recorded(exporter):
    session = FakeSession([[call_chunk("calculator")], [text_chunk("reply-secret")]])
    run_turn(session, "message-secret", FakeRegistry())
    for finished in exporter.get_finished_spans():
        assert "message-secret" not in str(dict(finished.attributes))
        assert "reply-secret" not in str(dict(finished.attributes))
        assert "2+2" not in str(dict(finished.attributes))