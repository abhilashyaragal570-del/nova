import threading

import pytest

from tools.base import Tool, ToolResult
from tools.registry import ToolRegistry
from workflows.executor import WorkflowExecutor, backoff_delay
from workflows.models import Task, TaskStatus, Workflow, WorkflowStatus


class EchoTool(Tool):
    name = "echo"
    read_only = True
    parameters = {"type": "object", "properties": {}, "required": []}

    def run(self, **kwargs) -> ToolResult:
        return ToolResult.success("ok")


class AlwaysFails(Tool):
    name = "bad"
    read_only = True
    parameters = {"type": "object", "properties": {}, "required": []}

    def run(self, **kwargs) -> ToolResult:
        return ToolResult.failure("nope")


def registry_with(*tools):
    reg = ToolRegistry()
    for t in tools:
        reg.register(t)
    return reg


# ---------- backoff_delay ----------

def test_backoff_grows_exponentially():
    assert [backoff_delay(n, base=1, factor=2, cap=100) for n in (1, 2, 3, 4)] == [1, 2, 4, 8]


def test_backoff_is_capped():
    assert backoff_delay(10, base=1, factor=2, cap=5) == 5


@pytest.mark.parametrize("attempt,base", [(0, 1), (-1, 1), (1, 0), (1, -2)])
def test_backoff_odd_input_means_no_wait(attempt, base):
    assert backoff_delay(attempt, base=base) == 0.0


# ---------- executor backoff ----------

def test_executor_waits_with_growing_delays_between_retries():
    waits = []
    wf = Workflow(goal="g", tasks=[Task("a", "x", "bad", max_attempts=4)])
    WorkflowExecutor(
        registry_with(AlwaysFails()),
        backoff_base=1.0,
        sleep=lambda s: waits.append(s) or False,
    ).run(wf)
    assert waits == [1.0, 2.0, 4.0]  # no wait after the final failure
    assert wf.get("a").status is TaskStatus.FAILED


def test_cancel_during_backoff_stops_the_workflow():
    wf = Workflow(
        goal="g",
        tasks=[Task("a", "x", "bad", max_attempts=3), Task("b", "y", "echo", depends_on=("a",))],
    )
    ex = WorkflowExecutor(registry_with(AlwaysFails(), EchoTool()), sleep=lambda s: True)
    ex.run(wf)
    assert wf.status is WorkflowStatus.CANCELLED
    assert wf.get("b").status is TaskStatus.CANCELLED


# ---------- deadline ----------

def test_deadline_cancels_remaining_tasks_and_keeps_results():
    clock = {"t": 0.0}

    class SlowEcho(EchoTool):
        def run(self, **kwargs):
            clock["t"] += 10  # each task "takes" 10 seconds
            return super().run(**kwargs)

    events = []
    wf = Workflow(
        goal="g",
        tasks=[
            Task("a", "x", "echo"),
            Task("b", "y", "echo", depends_on=("a",)),
            Task("c", "z", "echo", depends_on=("b",)),
        ],
    )
    WorkflowExecutor(
        registry_with(SlowEcho()),
        deadline_seconds=15,
        now=lambda: clock["t"],
        on_event=lambda k, t, d: events.append(k),
    ).run(wf)
    assert wf.get("a").status is TaskStatus.SUCCEEDED
    assert wf.get("b").status is TaskStatus.SUCCEEDED
    assert wf.get("c").status is TaskStatus.CANCELLED
    assert wf.status is WorkflowStatus.CANCELLED
    assert "timeout" in events


def test_no_deadline_means_no_timeout():
    wf = Workflow(goal="g", tasks=[Task("a", "x", "echo")])
    WorkflowExecutor(registry_with(EchoTool()), now=lambda: 10**9).run(wf)
    assert wf.status is WorkflowStatus.SUCCEEDED


# ---------- cancel event ----------

def test_cancel_event_set_before_run_runs_nothing():
    ev = threading.Event()
    ev.set()
    wf = Workflow(goal="g", tasks=[Task("a", "x", "echo")])
    WorkflowExecutor(registry_with(EchoTool()), cancel_event=ev).run(wf)
    assert wf.status is WorkflowStatus.CANCELLED
    assert wf.get("a").attempts == 0


def test_default_sleeper_wakes_when_event_is_set():
    ev = threading.Event()
    ev.set()
    ex = WorkflowExecutor(registry_with(EchoTool()), cancel_event=ev)
    assert ex._sleep(30) is True  # returns at once instead of waiting 30s