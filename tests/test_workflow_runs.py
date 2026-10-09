import threading
import time

import pytest

from tools.base import Tool, ToolResult
from tools.registry import ToolRegistry
from web.workflow_runs import Busy, WorkflowManager
from workflows.executor import WorkflowExecutor
from workflows.models import Task, Workflow
from workflows.planner import PlanError
from workflows.store import StoreError, WorkflowStore


class EchoTool(Tool):
    name = "echo"
    description = "echo"
    read_only = True
    parameters = {"type": "object", "properties": {}, "required": []}

    def __init__(self, gate=None):
        self.gate = gate
        self.calls = 0
        self.started = threading.Event()

    def run(self, **kwargs) -> ToolResult:
        self.calls += 1
        self.started.set()
        if self.gate is not None:
            self.gate.wait(5)
        return ToolResult.success("ok")


def default_plan(goal):
    return Workflow(
        goal, [Task("a", "first", "echo"), Task("b", "second", "echo", depends_on=("a",))]
    )


def build(tmp_path, tool=None, store=None, plan=default_plan):
    tool = tool or EchoTool()
    registry = ToolRegistry()
    registry.register(tool)
    store = store or WorkflowStore(tmp_path)

    class FakePlanner:
        def plan(self, goal):
            return plan(goal)

    manager = WorkflowManager(
        lambda write_tools: FakePlanner(),
        lambda on_event, cancel: WorkflowExecutor(
            registry, on_event=on_event, cancel_event=cancel
        ),
        lambda: store,
    )
    return manager, tool, store


def wait_state(manager, run_id, states, timeout=5):
    snap = None
    end = time.time() + timeout
    while time.time() < end:
        snap = manager.snapshot(run_id)
        if snap and snap["state"] in states:
            return snap
        time.sleep(0.01)
    raise AssertionError(f"timed out; last state: {snap and snap['state']}")


def test_plan_waits_for_approval_and_saves_nothing(tmp_path):
    manager, tool, store = build(tmp_path)
    run_id = manager.start("do it")
    snap = wait_state(manager, run_id, {"awaiting_approval"})
    assert snap["plan"].startswith("Plan for:")
    assert tool.calls == 0
    assert store.list_ids() == []


def test_approved_plan_runs_and_is_saved(tmp_path):
    manager, tool, store = build(tmp_path)
    run_id = manager.start("do it")
    wait_state(manager, run_id, {"awaiting_approval"})
    assert manager.approve(run_id, True) is True
    snap = wait_state(manager, run_id, {"done"})
    assert [t["status"] for t in snap["tasks"]] == ["succeeded", "succeeded"]
    assert snap["workflow_status"] == "succeeded"
    assert "succeeded" in snap["result"]
    assert store.list_ids() == [snap["workflow_id"]]


def test_declined_plan_never_runs_or_saves(tmp_path):
    manager, tool, store = build(tmp_path)
    run_id = manager.start("do it")
    wait_state(manager, run_id, {"awaiting_approval"})
    assert manager.approve(run_id, False) is True
    assert manager.snapshot(run_id)["state"] == "declined"
    assert tool.calls == 0
    assert store.list_ids() == []


def test_only_true_approves(tmp_path):
    manager, tool, _ = build(tmp_path)
    run_id = manager.start("do it")
    wait_state(manager, run_id, {"awaiting_approval"})
    manager.approve(run_id, "yes")
    assert manager.snapshot(run_id)["state"] == "declined"
    assert tool.calls == 0


def test_approve_unknown_id_or_twice_is_refused(tmp_path):
    manager, _, _ = build(tmp_path)
    run_id = manager.start("do it")
    wait_state(manager, run_id, {"awaiting_approval"})
    assert manager.approve("nope", True) is False
    assert manager.approve(run_id, True) is True
    assert manager.approve(run_id, True) is False
    wait_state(manager, run_id, {"done"})


def test_planning_error_is_reported(tmp_path):
    def bad_plan(goal):
        raise PlanError("no good")

    manager, _, _ = build(tmp_path, plan=bad_plan)
    run_id = manager.start("do it")
    snap = wait_state(manager, run_id, {"error"})
    assert "Could not plan: no good" in snap["error"]


def test_empty_goal_is_refused(tmp_path):
    manager, _, _ = build(tmp_path)
    with pytest.raises(ValueError):
        manager.start("   ")


def test_only_one_workflow_at_a_time(tmp_path):
    gate = threading.Event()
    manager, tool, _ = build(tmp_path, tool=EchoTool(gate))
    run_id = manager.start("do it")
    wait_state(manager, run_id, {"awaiting_approval"})
    manager.approve(run_id, True)
    assert tool.started.wait(5)
    with pytest.raises(Busy):
        manager.start("another")
    gate.set()
    wait_state(manager, run_id, {"done"})
    manager.start("another")  # free again


def test_cancel_while_running(tmp_path):
    gate = threading.Event()
    manager, tool, _ = build(tmp_path, tool=EchoTool(gate))
    run_id = manager.start("do it")
    wait_state(manager, run_id, {"awaiting_approval"})
    manager.approve(run_id, True)
    assert tool.started.wait(5)
    assert manager.cancel(run_id) is True
    gate.set()
    snap = wait_state(manager, run_id, {"cancelled"})
    assert snap["tasks"][1]["status"] == "cancelled"
    assert tool.calls == 1  # the second task never started


def test_cancel_while_waiting_for_approval_declines(tmp_path):
    manager, tool, _ = build(tmp_path)
    run_id = manager.start("do it")
    wait_state(manager, run_id, {"awaiting_approval"})
    assert manager.cancel(run_id) is True
    assert manager.snapshot(run_id)["state"] == "declined"
    assert tool.calls == 0


def test_save_failure_means_it_is_not_run(tmp_path):
    class BrokenStore(WorkflowStore):
        def save(self, workflow):
            raise StoreError("disk full")

    manager, tool, _ = build(tmp_path, store=BrokenStore(tmp_path))
    run_id = manager.start("do it")
    wait_state(manager, run_id, {"awaiting_approval"})
    manager.approve(run_id, True)
    snap = wait_state(manager, run_id, {"error"})
    assert "was not run" in snap["error"]
    assert tool.calls == 0


def test_resume_runs_only_the_unfinished_tasks(tmp_path):
    manager, tool, store = build(tmp_path)
    wf = Workflow(
        "g", [Task("a", "x", "echo"), Task("b", "y", "echo", depends_on=("a",))], id="wf1"
    )
    a = wf.get("a")
    a.start()
    a.succeed("kept")
    store.save(wf)
    run_id = manager.resume("wf1")
    snap = wait_state(manager, run_id, {"done"})
    assert snap["workflow_status"] == "succeeded"
    assert tool.calls == 1  # only b ran


def test_resume_refuses_finished_and_missing(tmp_path):
    manager, _, store = build(tmp_path)
    wf = Workflow("g", [Task("a", "x", "echo")], id="wf1")
    wf.get("a").start()
    wf.get("a").succeed("ok")
    wf.refresh_status()
    store.save(wf)
    with pytest.raises(ValueError):
        manager.resume("wf1")
    with pytest.raises(StoreError):
        manager.resume("nope")


def test_list_saved(tmp_path):
    manager, _, store = build(tmp_path)
    assert manager.list_saved() == []
    store.save(Workflow("g", [Task("a", "x", "echo")], id="wf1"))
    assert manager.list_saved() == [{"id": "wf1", "status": "pending", "goal": "g"}]


def test_snapshot_is_none_before_any_run(tmp_path):
    manager, _, _ = build(tmp_path)
    assert manager.snapshot() is None