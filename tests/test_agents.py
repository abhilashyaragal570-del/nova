import pytest

from agents.definitions import (
    AGENTS,
    AgentError,
    AgentSpec,
    build_registry,
    get_agent,
    list_agents,
)
from tools.base import Tool, ToolResult
from tools.policy import ToolPolicy
from tools.registry import ToolRegistry


class FakeTool(Tool):
    def __init__(self, name):
        self.name = name
        self.description = "fake"

    def run(self, **kwargs):
        return ToolResult.success("ok")


def make_source(names, policy=None, timeout=30.0):
    source = ToolRegistry(policy=policy, default_timeout=timeout)
    for name in names:
        source.register(FakeTool(name))
    return source


ALL_TOOLS = ["calculator", "web_search", "search_documents", "write_file"]


def test_registry_has_only_the_agents_tools():
    restricted = build_registry(get_agent("notes"), make_source(ALL_TOOLS))
    assert [t.name for t in restricted.all()] == ["search_documents"]


def test_other_tools_cannot_be_called():
    restricted = build_registry(get_agent("notes"), make_source(ALL_TOOLS))
    assert restricted.execute("search_documents", {}).ok
    result = restricted.execute("write_file", {})
    assert not result.ok
    assert "Unknown tool" in result.error


def test_policy_and_timeout_are_shared():
    policy = ToolPolicy()
    source = make_source(ALL_TOOLS, policy=policy, timeout=12.0)
    restricted = build_registry(get_agent("researcher"), source)
    assert restricted.policy is policy
    assert restricted.default_timeout == 12.0


def test_a_missing_tool_is_an_error():
    spec = AgentSpec("x", "d", "p", frozenset({"nope"}))
    with pytest.raises(AgentError):
        build_registry(spec, make_source(ALL_TOOLS))


def test_get_agent_finds_by_name():
    assert get_agent("notes").name == "notes"
    assert get_agent("  Researcher ").name == "researcher"


@pytest.mark.parametrize("name", ["nope", "", None])
def test_unknown_agent_is_an_error(name):
    with pytest.raises(AgentError):
        get_agent(name)


def test_list_agents_matches_the_table():
    assert [a.name for a in list_agents()] == sorted(AGENTS)


def test_built_in_agents_are_well_formed():
    for key, spec in AGENTS.items():
        assert spec.name == key
        assert spec.description.strip()
        assert spec.system_prompt.strip()
        assert spec.tools
        assert not (spec.tools & {"write_file", "api_request"})


def test_built_in_agents_build_from_a_full_registry():
    needed = sorted(set().union(*(spec.tools for spec in AGENTS.values())))
    source = make_source(needed)
    for spec in AGENTS.values():
        restricted = build_registry(spec, source)
        assert {t.name for t in restricted.all()} == set(spec.tools)