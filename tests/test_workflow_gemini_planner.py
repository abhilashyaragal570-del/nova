import json
from types import SimpleNamespace

import pytest

from tools.base import Tool, ToolResult
from tools.registry import ToolRegistry
from workflows.executor import WorkflowExecutor
from workflows.gemini_planner import describe_tool, make_planner, tool_descriptions
from workflows.models import WorkflowStatus
from workflows.planner import PlanError


class Reader(Tool):
    name = "read_note"
    description = "Read a note from disk"
    read_only = True
    parameters = {
        "type": "object",
        "properties": {"path": {"type": "string"}, "limit": {"type": "integer"}},
        "required": ["path"],
    }

    def run(self, **kwargs) -> ToolResult:
        return ToolResult.success("note text")


class Writer(Tool):
    name = "write_note"
    description = "Write a note to disk"
    read_only = False
    parameters = {"type": "object", "properties": {}, "required": []}

    def run(self, **kwargs) -> ToolResult:
        return ToolResult.success("written")


def registry():
    reg = ToolRegistry()
    reg.register(Reader())
    reg.register(Writer())
    return reg


def answer(*tasks):
    return json.dumps({"tasks": list(tasks)})


def test_describe_lists_arguments_and_marks_required():
    text = describe_tool(Reader())
    assert text.startswith("Read a note from disk")
    assert "path (required)" in text
    assert "limit" in text and "limit (required)" not in text


def test_describe_survives_a_bare_tool():
    assert describe_tool(SimpleNamespace(name="x")) == "(no description)"


def test_only_read_only_tools_by_default():
    assert set(tool_descriptions(registry())) == {"read_note"}


def test_write_tools_can_be_included_on_purpose():
    assert set(tool_descriptions(registry(), read_only_only=False)) == {"read_note", "write_note"}


def test_plan_from_registry_runs_end_to_end():
    reg = registry()
    text = answer(
        {"id": "a", "description": "read", "tool": "read_note", "arguments": {"path": "n.txt"}},
        {
            "id": "b",
            "description": "read again",
            "tool": "read_note",
            "arguments": {"path": "n.txt"},
            "depends_on": ["a"],
        },
    )
    wf = make_planner(reg, generate=lambda prompt: text).plan("read my note")
    WorkflowExecutor(reg).run(wf)
    assert wf.status is WorkflowStatus.SUCCEEDED


def test_write_tool_is_refused_by_default():
    text = answer({"id": "a", "description": "write", "tool": "write_note"})
    with pytest.raises(PlanError):
        make_planner(registry(), generate=lambda prompt: text, retries=0).plan("write a note")


def test_prompt_shows_only_offered_tools_with_arguments():
    seen = []

    def generate(prompt):
        seen.append(prompt)
        return answer({"id": "a", "description": "d"})

    make_planner(registry(), generate=generate).plan("goal")
    assert "read_note" in seen[0]
    assert "path (required)" in seen[0]
    assert "write_note" not in seen[0]