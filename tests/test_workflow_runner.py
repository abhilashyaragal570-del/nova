import json

import pytest

from tools.base import Tool, ToolResult
from tools.policy import ToolPolicy
from tools.registry import ToolRegistry
from workflows.__main__ import main
from workflows.executor import WorkflowExecutor
from workflows.gemini_planner import make_planner
from workflows.models import Task, TaskStatus, Workflow, WorkflowStatus
from workflows.planner import Planner
from workflows.runner import format_plan, list_runs, resume_workflow, run_goal
from workflows.store import WorkflowStore

PLAN = json.dumps({"tasks": [{"id": "a", "description": "do a", "tool": "echo"}]})
WRITE_PLAN = json.dumps(
    {
        "tasks": [
            {
                "id": "a",
                "description": "write it",
                "tool": "write_note",
                "arguments": {"text": "hi"},
            }
        ]
    }
)
PARAMS = {"type": "object", "properties": {}, "required": []}


class Echo(Tool):
    name = "echo"
    description = "Echo"
    read_only = True
    parameters = PARAMS

    def __init__(self):
        self.calls = 0

    def run(self, **kwargs) -> ToolResult:
        self.calls += 1
        return ToolResult.success("ok")


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


class Interrupter(Tool):
    name = "interrupt"
    description = "Simulates Ctrl+C"
    read_only = True
    parameters = PARAMS

    def run(self, **kwargs) -> ToolResult:
        raise KeyboardInterrupt


def registry(*tools, confirm=None):
    reg = ToolRegistry(policy=ToolPolicy(confirm=confirm))
    for tool in tools:
        reg.register(tool)
    return reg


def no_wait(seconds):
    return False


def factory(reg):
    return lambda on_event: WorkflowExecutor(reg, on_event=on_event, sleep=no_wait)


def fixed(text):
    return lambda prompt: text


def planner_for(text, tools=None):
    return Planner(fixed(text), tools or {"echo": "Echo"}, retries=0)


def test_format_plan_lists_tasks():
    wf = Workflow(
        "g",
        [
            Task("a", "read", "echo", arguments={"text": "x"}),
            Task("b", "summarize", depends_on=("a",)),
        ],
    )
    text = format_plan(wf)
    assert "Plan for: g" in text
    assert '1. [tool echo] {"text": "x"} - read' in text
    assert "2. [model step] after a - summarize" in text


def test_declined_preview_runs_nothing(tmp_path):
    echo = Echo()
    store = WorkflowStore(tmp_path)
    said = []
    result = run_goal(
        "g", planner_for(PLAN), factory(registry(echo)), store, ask=lambda p: "n", say=said.append
    )
    assert result is None
    assert echo.calls == 0
    assert store.list_ids() == []
    assert any("Not run" in line for line in said)


@pytest.mark.parametrize("answer", ["", "n", "no", "maybe", "yep"])
def test_only_yes_runs_the_plan(tmp_path, answer):
    echo = Echo()
    result = run_goal(
        "g",
        planner_for(PLAN),
        factory(registry(echo)),
        WorkflowStore(tmp_path),
        ask=lambda p: answer,
        say=lambda s: None,
    )
    assert result is None
    assert echo.calls == 0


def test_end_of_input_counts_as_no(tmp_path):
    echo = Echo()

    def ask(prompt):
        raise EOFError

    result = run_goal(
        "g",
        planner_for(PLAN),
        factory(registry(echo)),
        WorkflowStore(tmp_path),
        ask=ask,
        say=lambda s: None,
    )
    assert result is None
    assert echo.calls == 0


@pytest.mark.parametrize("answer", ["y", "Y", " yes "])
def test_yes_answers_run_the_plan(tmp_path, answer):
    echo = Echo()
    run_goal(
        "g",
        planner_for(PLAN),
        factory(registry(echo)),
        WorkflowStore(tmp_path),
        ask=lambda p: answer,
        say=lambda s: None,
    )
    assert echo.calls == 1


def test_confirmed_plan_runs_saves_and_logs(tmp_path):
    store = WorkflowStore(tmp_path)
    said = []
    result = run_goal(
        "g",
        planner_for(PLAN),
        factory(registry(Echo())),
        store,
        ask=lambda p: "y",
        say=said.append,
    )
    assert result.status is WorkflowStatus.SUCCEEDED
    assert store.load(result.id).status is WorkflowStatus.SUCCEEDED
    assert [e["kind"] for e in store.read_events(result.id)] == ["start", "succeed"]
    assert any("succeeded" in line for line in said)


def test_plan_failure_is_reported(tmp_path):
    store = WorkflowStore(tmp_path)
    said = []
    planner = Planner(fixed("not json"), {"echo": "Echo"}, retries=0)
    result = run_goal(
        "g", planner, factory(registry(Echo())), store, ask=lambda p: "y", say=said.append
    )
    assert result is None
    assert store.list_ids() == []
    assert any("Could not plan" in line for line in said)


def test_write_step_still_asks_during_the_run(tmp_path):
    writer = Writer()
    reg = registry(Echo(), writer, confirm=lambda name, args: False)
    planner = make_planner(reg, generate=fixed(WRITE_PLAN), read_only_only=False, retries=0)
    result = run_goal(
        "write it",
        planner,
        factory(reg),
        WorkflowStore(tmp_path),
        ask=lambda p: "y",
        say=lambda s: None,
    )
    assert result.status is WorkflowStatus.FAILED
    assert result.get("a").attempts == 1
    assert writer.written == []


def test_resume_finishes_without_rerunning_done_tasks(tmp_path):
    store = WorkflowStore(tmp_path)
    wf = Workflow(
        "g",
        [Task("a", "x", "echo"), Task("b", "y", "echo", depends_on=("a",))],
        id="wf1",
    )
    a = wf.get("a")
    a.start()
    a.succeed("kept")
    wf.get("b").start()  # crash while b was running
    store.save(wf)
    echo = Echo()
    result = resume_workflow("wf1", factory(registry(echo)), store, say=lambda s: None)
    assert result.status is WorkflowStatus.SUCCEEDED
    assert result.get("a").output == "kept"
    assert echo.calls == 1


def test_resume_unknown_id_is_reported(tmp_path):
    said = []
    result = resume_workflow(
        "nope", factory(registry(Echo())), WorkflowStore(tmp_path), say=said.append
    )
    assert result is None
    assert any("no saved workflow" in line for line in said)


def test_resume_of_finished_workflow_runs_nothing(tmp_path):
    store = WorkflowStore(tmp_path)
    wf = Workflow("g", [Task("a", "x", "echo")], id="wf1")
    wf.get("a").start()
    wf.get("a").succeed("done")
    wf.refresh_status()
    store.save(wf)
    echo = Echo()
    said = []
    result = resume_workflow("wf1", factory(registry(echo)), store, say=said.append)
    assert result.status is WorkflowStatus.SUCCEEDED
    assert echo.calls == 0
    assert any("already succeeded" in line for line in said)


def test_interrupt_saves_progress_and_can_resume(tmp_path):
    store = WorkflowStore(tmp_path)
    said = []
    plan = json.dumps({"tasks": [{"id": "a", "description": "stop", "tool": "interrupt"}]})
    result = run_goal(
        "g",
        planner_for(plan, {"interrupt": "Simulates Ctrl+C"}),
        factory(registry(Interrupter())),
        store,
        ask=lambda p: "y",
        say=said.append,
    )
    assert any("--resume" in line and result.id in line for line in said)
    assert store.load(result.id).get("a").status is TaskStatus.PENDING


def test_list_runs_when_empty(tmp_path):
    said = []
    list_runs(WorkflowStore(tmp_path), say=said.append)
    assert said == ["No saved workflows."]


def test_list_runs_shows_saved_and_unreadable(tmp_path):
    store = WorkflowStore(tmp_path)
    store.save(Workflow("find the news", [Task("a", "x", "echo")], id="wf1"))
    (tmp_path / "runs" / "bad.json").write_text("{not json", encoding="utf-8")
    said = []
    list_runs(store, say=said.append)
    assert any("wf1" in line and "find the news" in line for line in said)
    assert any("bad" in line and "unreadable" in line for line in said)


def test_main_without_arguments_is_an_error():
    with pytest.raises(SystemExit) as exc:
        main([])
    assert exc.value.code == 2


def test_main_rejects_goal_together_with_resume():
    with pytest.raises(SystemExit) as exc:
        main(["--resume", "wf1", "some goal"])
    assert exc.value.code == 2


def test_main_list_needs_no_model(tmp_path, capsys):
    assert main(["--list"], store=WorkflowStore(tmp_path)) == 0
    assert "No saved workflows." in capsys.readouterr().out