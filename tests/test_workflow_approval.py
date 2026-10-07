import json

import pytest

from tools.base import Tool, ToolResult
from tools.policy import ToolPolicy
from tools.registry import ToolRegistry
from workflows.executor import WorkflowExecutor
from workflows.gemini_planner import make_planner
from workflows.models import Task, TaskStatus, Workflow, WorkflowStatus


class Reader(Tool):
    name = "read_note"
    description = "Read a note"
    read_only = True
    parameters = {"type": "object", "properties": {}, "required": []}

    def run(self, **kwargs) -> ToolResult:
        return ToolResult.success("note")


class Writer(Tool):
    name = "write_note"
    description = "Write a note"
    read_only = False
    parameters = {
        "type": "object",
        "properties": {"text": {"type": "string"}},
        "required": [],
    }

    def __init__(self):
        self.written = []

    def run(self, **kwargs) -> ToolResult:
        self.written.append(kwargs)
        return ToolResult.success("written")


class Flaky(Tool):
    name = "flaky"
    description = "Fails once, then works"
    read_only = True
    parameters = {"type": "object", "properties": {}, "required": []}

    def __init__(self):
        self.calls = 0

    def run(self, **kwargs) -> ToolResult:
        self.calls += 1
        if self.calls == 1:
            return ToolResult.failure("try again")
        return ToolResult.success("ok")


def make_registry(confirm=None, extra=()):
    reg = ToolRegistry(policy=ToolPolicy(confirm=confirm))
    writer = Writer()
    reg.register(Reader())
    reg.register(writer)
    for tool in extra:
        reg.register(tool)
    return reg, writer


def no_wait(seconds):
    return False


def write_workflow(attempts=3):
    return Workflow(
        "g",
        [Task("a", "write", "write_note", arguments={"text": "hi"}, max_attempts=attempts)],
    )


def test_refusal_result_is_marked():
    result = ToolResult.refusal("no")
    assert result.ok is False
    assert result.refused is True
    assert result.error == "no"


def test_ordinary_results_are_not_marked():
    assert ToolResult.failure("x").refused is False
    assert ToolResult.success(1).refused is False


def test_registry_marks_policy_refusals():
    reg = ToolRegistry(policy=ToolPolicy(blocked={"read_note"}))
    reg.register(Reader())
    result = reg.execute("read_note", {})
    assert result.ok is False
    assert result.refused is True


def test_registry_does_not_mark_unknown_tool_as_refused():
    result = ToolRegistry().execute("nope", {})
    assert result.ok is False
    assert result.refused is False


def test_declined_write_is_asked_once_and_not_retried():
    asked = []

    def confirm(name, args):
        asked.append((name, args))
        return False

    reg, writer = make_registry(confirm)
    wf = write_workflow()
    WorkflowExecutor(reg, sleep=no_wait).run(wf)
    assert len(asked) == 1
    assert wf.get("a").status is TaskStatus.FAILED
    assert wf.get("a").attempts == 1
    assert "declined" in wf.get("a").error
    assert writer.written == []
    assert wf.status is WorkflowStatus.FAILED


def test_approved_write_runs():
    asked = []

    def confirm(name, args):
        asked.append((name, args))
        return True

    reg, writer = make_registry(confirm)
    wf = write_workflow()
    WorkflowExecutor(reg, sleep=no_wait).run(wf)
    assert asked == [("write_note", {"text": "hi"})]
    assert writer.written == [{"text": "hi"}]
    assert wf.status is WorkflowStatus.SUCCEEDED


def test_no_confirm_configured_is_not_retried():
    reg, writer = make_registry(None)
    wf = write_workflow()
    WorkflowExecutor(reg, sleep=no_wait).run(wf)
    assert wf.get("a").status is TaskStatus.FAILED
    assert wf.get("a").attempts == 1
    assert "needs user confirmation" in wf.get("a").error
    assert writer.written == []


def test_broken_confirm_is_not_retried():
    calls = []

    def confirm(name, args):
        calls.append(1)
        raise RuntimeError("boom")

    reg, writer = make_registry(confirm)
    wf = write_workflow()
    WorkflowExecutor(reg, sleep=no_wait).run(wf)
    assert len(calls) == 1
    assert wf.get("a").attempts == 1
    assert writer.written == []


@pytest.mark.parametrize("answer", ["yes", 1, None])
def test_only_true_counts_as_approval(answer):
    reg, writer = make_registry(lambda name, args: answer)
    wf = write_workflow()
    WorkflowExecutor(reg, sleep=no_wait).run(wf)
    assert wf.get("a").status is TaskStatus.FAILED
    assert writer.written == []


def test_read_only_task_never_asks():
    asked = []
    reg, writer = make_registry(lambda name, args: asked.append(name) or True)
    wf = Workflow("g", [Task("a", "read", "read_note")])
    WorkflowExecutor(reg).run(wf)
    assert wf.status is WorkflowStatus.SUCCEEDED
    assert asked == []


def test_ordinary_failures_are_still_retried():
    flaky = Flaky()
    reg, writer = make_registry(None, extra=[flaky])
    wf = Workflow("g", [Task("a", "try", "flaky", max_attempts=2)])
    WorkflowExecutor(reg, sleep=no_wait).run(wf)
    assert wf.status is WorkflowStatus.SUCCEEDED
    assert wf.get("a").attempts == 2
    assert flaky.calls == 2


def test_decline_skips_dependents():
    reg, writer = make_registry(lambda name, args: False)
    wf = Workflow(
        "g",
        [
            Task("a", "write", "write_note", arguments={"text": "hi"}),
            Task("b", "read", "read_note", depends_on=("a",)),
        ],
    )
    WorkflowExecutor(reg, sleep=no_wait).run(wf)
    assert wf.get("a").status is TaskStatus.FAILED
    assert wf.get("b").status is TaskStatus.SKIPPED


def _planned_write_workflow(reg):
    text = json.dumps(
        {
            "tasks": [
                {
                    "id": "a",
                    "description": "write",
                    "tool": "write_note",
                    "arguments": {"text": "hi"},
                }
            ]
        }
    )
    return make_planner(reg, generate=lambda prompt: text, read_only_only=False).plan(
        "write a note"
    )


def test_planned_write_runs_when_approved():
    reg, writer = make_registry(lambda name, args: True)
    wf = _planned_write_workflow(reg)
    WorkflowExecutor(reg).run(wf)
    assert wf.status is WorkflowStatus.SUCCEEDED
    assert writer.written == [{"text": "hi"}]


def test_planned_write_does_not_run_when_declined():
    reg, writer = make_registry(lambda name, args: False)
    wf = _planned_write_workflow(reg)
    WorkflowExecutor(reg).run(wf)
    assert wf.status is WorkflowStatus.FAILED
    assert writer.written == []