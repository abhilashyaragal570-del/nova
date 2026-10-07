import json

import pytest

from tools.base import Tool, ToolResult
from tools.registry import ToolRegistry
from workflows.executor import WorkflowExecutor
from workflows.models import Task, TaskStatus, Workflow, WorkflowStatus
from workflows.store import StoreError, WorkflowStore


class EchoTool(Tool):
    name = "echo"
    read_only = True
    parameters = {"type": "object", "properties": {}, "required": []}

    def run(self, **kwargs) -> ToolResult:
        return ToolResult.success("ok")


def make():
    return Workflow(
        goal="g",
        tasks=[Task("a", "x", "echo"), Task("b", "y", "echo", depends_on=("a",))],
        id="wf1",
    )


def test_save_and_load_round_trip(tmp_path):
    store = WorkflowStore(tmp_path)
    wf = make()
    a = wf.get("a")
    a.start()
    a.succeed("result")
    store.save(wf)
    loaded = store.load("wf1")
    assert loaded.to_dict() == wf.to_dict()


def test_save_leaves_no_temp_files(tmp_path):
    store = WorkflowStore(tmp_path)
    store.save(make())
    assert [p.name for p in (tmp_path / "runs").iterdir()] == ["wf1.json"]


def test_save_overwrites_previous_version(tmp_path):
    store = WorkflowStore(tmp_path)
    wf = make()
    store.save(wf)
    wf.get("a").start()
    store.save(wf)
    assert store.load("wf1", resume=False).get("a").status is TaskStatus.RUNNING


def test_unserializable_output_is_refused_and_old_file_survives(tmp_path):
    store = WorkflowStore(tmp_path)
    wf = make()
    store.save(wf)
    a = wf.get("a")
    a.start()
    a.succeed(object())
    with pytest.raises(StoreError):
        store.save(wf)
    assert store.load("wf1").get("a").status is TaskStatus.PENDING


@pytest.mark.parametrize("bad", ["", "..", "../evil", "a/b", "a\\b", "x" * 100, "a.b", None, 5])
def test_bad_ids_are_rejected(tmp_path, bad):
    store = WorkflowStore(tmp_path)
    with pytest.raises(StoreError):
        store.load(bad)
    with pytest.raises(StoreError):
        store.append_event(bad, "start", "a")


def test_load_missing_workflow(tmp_path):
    with pytest.raises(StoreError):
        WorkflowStore(tmp_path).load("nope")


def test_load_corrupt_file(tmp_path):
    store = WorkflowStore(tmp_path)
    (tmp_path / "runs").mkdir()
    (tmp_path / "runs" / "bad.json").write_text("{not json", encoding="utf-8")
    with pytest.raises(StoreError):
        store.load("bad")


def test_load_structurally_invalid_workflow(tmp_path):
    store = WorkflowStore(tmp_path)
    (tmp_path / "runs").mkdir()
    (tmp_path / "runs" / "bad.json").write_text(json.dumps({"id": "bad"}), encoding="utf-8")
    with pytest.raises(StoreError):
        store.load("bad")


def test_resume_resets_running_tasks(tmp_path):
    store = WorkflowStore(tmp_path)
    wf = make()
    wf.get("a").start()  # simulate a crash mid-task
    wf.refresh_status()
    store.save(wf)
    loaded = store.load("wf1")
    assert loaded.get("a").status is TaskStatus.PENDING
    assert loaded.get("a").attempts == 0
    assert loaded.status is WorkflowStatus.PENDING


def test_load_without_resume_keeps_running(tmp_path):
    store = WorkflowStore(tmp_path)
    wf = make()
    wf.get("a").start()
    store.save(wf)
    assert store.load("wf1", resume=False).get("a").status is TaskStatus.RUNNING


def test_list_ids(tmp_path):
    store = WorkflowStore(tmp_path)
    assert store.list_ids() == []
    store.save(make())
    assert store.list_ids() == ["wf1"]


def test_event_log_round_trip(tmp_path):
    store = WorkflowStore(tmp_path)
    store.append_event("wf1", "start", "a", "attempt 1/1")
    store.append_event("wf1", "succeed", "a")
    events = store.read_events("wf1")
    assert [e["kind"] for e in events] == ["start", "succeed"]
    assert events[0]["detail"] == "attempt 1/1"
    assert events[0]["ts"] > 0


def test_damaged_log_line_is_skipped(tmp_path):
    store = WorkflowStore(tmp_path)
    store.append_event("wf1", "start", "a")
    with open(tmp_path / "logs" / "wf1.jsonl", "a", encoding="utf-8") as f:
        f.write("{broken\n")
    store.append_event("wf1", "succeed", "a")
    assert [e["kind"] for e in store.read_events("wf1")] == ["start", "succeed"]


def test_read_events_without_log_is_empty(tmp_path):
    assert WorkflowStore(tmp_path).read_events("wf1") == []


def test_executor_run_is_saved_and_logged(tmp_path):
    store = WorkflowStore(tmp_path)
    wf = make()
    reg = ToolRegistry()
    reg.register(EchoTool())
    WorkflowExecutor(reg, on_event=store.listener(wf)).run(wf)
    store.save(wf)
    loaded = store.load("wf1")
    assert loaded.status is WorkflowStatus.SUCCEEDED
    kinds = [e["kind"] for e in store.read_events("wf1")]
    assert kinds == ["start", "succeed", "start", "succeed"]


def test_resumed_workflow_finishes_without_rerunning_done_tasks(tmp_path):
    store = WorkflowStore(tmp_path)
    wf = make()
    a = wf.get("a")
    a.start()
    a.succeed("kept")
    wf.get("b").start()  # crash while b was running
    store.save(wf)

    loaded = store.load("wf1")
    reg = ToolRegistry()
    reg.register(EchoTool())
    WorkflowExecutor(reg).run(loaded)
    assert loaded.status is WorkflowStatus.SUCCEEDED
    assert loaded.get("a").attempts == 1  # not run again
    assert loaded.get("a").output == "kept"