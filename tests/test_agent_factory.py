import pytest

from agents.definitions import AgentError, AgentSpec, get_agent
from agents.factory import new_agent_chat
from tools.base import Tool, ToolResult
from tools.registry import ToolRegistry


class FakeTool(Tool):
    def __init__(self, name):
        self.name = name
        self.description = "fake"

    def run(self, **kwargs):
        return ToolResult.success("ok")


class FakeChats:
    def __init__(self):
        self.kwargs = None

    def create(self, **kwargs):
        self.kwargs = kwargs
        return "fake-chat"


class FakeClient:
    def __init__(self):
        self.chats = FakeChats()


def make_source(names):
    source = ToolRegistry()
    for name in names:
        source.register(FakeTool(name))
    return source


ALL_TOOLS = ["calculator", "web_search", "search_documents", "write_file"]


def test_chat_uses_the_agents_prompt_and_model():
    client = FakeClient()
    spec = get_agent("notes")
    chat, _ = new_agent_chat(client, "test-model", spec, make_source(ALL_TOOLS))
    assert chat == "fake-chat"
    assert client.chats.kwargs["model"] == "test-model"
    config = client.chats.kwargs["config"]
    assert config.system_instruction == spec.system_prompt


def test_returned_registry_holds_only_the_agents_tools():
    client = FakeClient()
    _, registry = new_agent_chat(
        client, "m", get_agent("researcher"), make_source(ALL_TOOLS)
    )
    assert {t.name for t in registry.all()} == {"web_search", "calculator"}


def test_gemini_is_told_about_only_the_agents_tools():
    client = FakeClient()
    new_agent_chat(client, "m", get_agent("notes"), make_source(ALL_TOOLS))
    config = client.chats.kwargs["config"]
    declared = [
        d.name
        for tool in config.tools
        for d in tool.function_declarations
    ]
    assert declared == ["search_documents"]


def test_history_is_passed_through():
    client = FakeClient()
    history = ["a", "b"]
    new_agent_chat(client, "m", get_agent("notes"), make_source(ALL_TOOLS), history)
    assert client.chats.kwargs["history"] == history


def test_history_defaults_to_empty():
    client = FakeClient()
    new_agent_chat(client, "m", get_agent("notes"), make_source(ALL_TOOLS))
    assert client.chats.kwargs["history"] == []


def test_missing_tool_fails_before_any_chat_is_made():
    client = FakeClient()
    spec = AgentSpec("x", "d", "p", frozenset({"nope"}))
    with pytest.raises(AgentError):
        new_agent_chat(client, "m", spec, make_source(ALL_TOOLS))
    assert client.chats.kwargs is None