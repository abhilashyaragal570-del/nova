from tools.base import Tool, ToolResult
from tools.policy import ToolPolicy
from tools.registry import ToolRegistry
from workflows.executor import WorkflowExecutor
from workflows.models import Task, TaskStatus, Workflow, WorkflowStatus


class EchoTool(Tool):
    name = "echo"
    read_only = True
    parameters = {"type": "object", "properties": {}, "required": []}

    def run(self, **kwargs) -> ToolResult:
        return ToolResult.success(kwargs.get("text", ""))


class FlakyTool(Tool):
    """Fails the first `fail_times` calls, then succeeds."""

    name = "flaky"
    read_only = True
    parameters = {"type": "object", "properties": {}, "required": []}

    def __init__(self, fail_times):
        self.fail_times = fail_times
        self.calls = 0

    def run(self, **kwargs) -> ToolResult:
        self.calls += 1
        if self.calls <= self.fail_times:
            return ToolResult.failure("temporary problem")
        return ToolResult.success("finally")


class WriterTool(Tool):
    name = "writer"
    read_only = False
    parameters = {"type": "object", "properties": {}, "required": []}

    def __init__(self):
        self.calls = 0

    def run(self, **kwargs) -> ToolResult:
        self.calls += 1
        return ToolResult.success("wrote")


def registry_with(*tools, policy=None):
    reg = ToolRegistry(policy=policy)
    for t in tools:
        reg.register(t)
    return reg


def test_runs_tasks_in_dependency_order():
    events = []
    wf = Workflow(
        goal="g",
        tasks=[
            Task("c", "third", "echo", {"text": "c"}, depends_on=("b",)),
            Task("b", "second", "echo", {"text": "b"}, depends_on=("a",)),
            Task("a", "first", "echo", {"text": "a"}),
        ],
    )
    ex = WorkflowExecutor(
        registry_with(EchoTool()), on_event=lambda k, t, d: events.append((k, t))
    )
    ex.run(wf)
    assert [t for k, t in events if k == "start"] == ["a", "b", "c"]
    assert wf.status is WorkflowStatus.SUCCEEDED
    assert wf.get("c").output == "c"


def test_failed_task_skips_dependents_and_fails_workflow():
    wf = Workflow(
        goal="g",
        tasks=[
            Task("a", "x", "nonexistent"),
            Task("b", "y", "echo", depends_on=("a",)),
            Task("c", "z", "echo"),  # independent, still runs
        ],
    )
    WorkflowExecutor(registry_with(EchoTool())).run(wf)
    assert wf.get("a").status is TaskStatus.FAILED
    assert wf.get("b").status is TaskStatus.SKIPPED
    assert wf.get("c").status is TaskStatus.SUCCEEDED
    assert wf.status is WorkflowStatus.FAILED


def test_retry_succeeds_when_attempts_remain():
    flaky = FlakyTool(fail_times=2)
    wf = Workflow(goal="g", tasks=[Task("a", "x", "flaky", max_attempts=3)])
    WorkflowExecutor(registry_with(flaky), backoff_base=0).run(wf)
    assert flaky.calls == 3
    assert wf.get("a").status is TaskStatus.SUCCEEDED
    assert wf.get("a").attempts == 3


def test_retry_gives_up_after_max_attempts():
    flaky = FlakyTool(fail_times=10)
    wf = Workflow(goal="g", tasks=[Task("a", "x", "flaky", max_attempts=2)])
    WorkflowExecutor(registry_with(flaky), backoff_base=0).run(wf)
    assert flaky.calls == 2
    assert wf.get("a").status is TaskStatus.FAILED
    assert wf.status is WorkflowStatus.FAILED


def test_task_without_tool_fails_clearly():
    wf = Workflow(goal="g", tasks=[Task("a", "model step")])
    WorkflowExecutor(registry_with(EchoTool())).run(wf)
    assert wf.get("a").status is TaskStatus.FAILED
    assert "no tool" in wf.get("a").error


def test_policy_applies_to_workflow_tasks():
    writer = WriterTool()
    declined = ToolPolicy(confirm=lambda name, args: False)
    wf = Workflow(goal="g", tasks=[Task("a", "write", "writer")])
    WorkflowExecutor(registry_with(writer, policy=declined)).run(wf)
    assert writer.calls == 0
    assert wf.get("a").status is TaskStatus.FAILED
    assert "declined" in wf.get("a").error


def test_approved_write_runs():
    writer = WriterTool()
    approved = ToolPolicy(confirm=lambda name, args: True)
    wf = Workflow(goal="g", tasks=[Task("a", "write", "writer")])
    WorkflowExecutor(registry_with(writer, policy=approved)).run(wf)
    assert writer.calls == 1
    assert wf.status is WorkflowStatus.SUCCEEDED


def test_cancel_before_start_runs_nothing():
    echo_calls = []

    class Counting(EchoTool):
        def run(self, **kwargs):
            echo_calls.append(1)
            return super().run(**kwargs)

    wf = Workflow(goal="g", tasks=[Task("a", "x", "echo"), Task("b", "y", "echo")])
    WorkflowExecutor(registry_with(Counting()), should_cancel=lambda: True).run(wf)
    assert echo_calls == []
    assert wf.status is WorkflowStatus.CANCELLED
    assert all(t.status is TaskStatus.CANCELLED for t in wf.tasks)


def test_cancel_midway_keeps_finished_results():
    state = {"n": 0}

    def cancel_after_first():
        state["n"] += 1
        return state["n"] > 1  # false on the first check, true afterwards

    wf = Workflow(
        goal="g",
        tasks=[Task("a", "x", "echo", {"text": "A"}), Task("b", "y", "echo", depends_on=("a",))],
    )
    WorkflowExecutor(registry_with(EchoTool()), should_cancel=cancel_after_first).run(wf)
    assert wf.get("a").status is TaskStatus.SUCCEEDED
    assert wf.get("a").output == "A"
    assert wf.get("b").status is TaskStatus.CANCELLED


def test_broken_event_handler_does_not_break_the_run():
    def bad(kind, task_id, detail):
        raise RuntimeError("listener bug")

    wf = Workflow(goal="g", tasks=[Task("a", "x", "echo")])
    WorkflowExecutor(registry_with(EchoTool()), on_event=bad).run(wf)
    assert wf.status is WorkflowStatus.SUCCEEDED


def test_registry_that_raises_is_contained():
    class Exploding:
        def execute(self, name, arguments):
            raise RuntimeError("registry bug")

    wf = Workflow(goal="g", tasks=[Task("a", "x", "echo")])
    WorkflowExecutor(Exploding()).run(wf)
    assert wf.get("a").status is TaskStatus.FAILED
    assert "registry bug" in wf.get("a").error


def test_finished_workflow_is_not_rerun():
    echo = EchoTool()
    wf = Workflow(goal="g", tasks=[Task("a", "x", "echo")])
    ex = WorkflowExecutor(registry_with(echo))
    ex.run(wf)
    ex.run(wf)
    assert wf.get("a").attempts == 1