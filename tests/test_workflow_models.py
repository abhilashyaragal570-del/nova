import json

import pytest

from workflows.models import (
    MAX_TASKS,
    InvalidTransition,
    Task,
    TaskStatus,
    Workflow,
    WorkflowError,
    WorkflowStatus,
)


def make():
    return Workflow(
        goal="add numbers",
        tasks=[
            Task("a", "first", "calculator", {"expression": "1+1"}),
            Task("b", "second", depends_on=("a",)),
            Task("c", "third", depends_on=("b",)),
        ],
    )


# ---------- Task validation ----------

def test_task_requires_id_and_description():
    with pytest.raises(WorkflowError):
        Task("", "x")
    with pytest.raises(WorkflowError):
        Task("a", "  ")


def test_task_cannot_depend_on_itself():
    with pytest.raises(WorkflowError):
        Task("a", "x", depends_on=("a",))


def test_duplicate_dependencies_are_rejected():
    with pytest.raises(WorkflowError):
        Task("b", "x", depends_on=("a", "a"))


def test_max_attempts_must_be_positive():
    with pytest.raises(WorkflowError):
        Task("a", "x", max_attempts=0)


# ---------- Task transitions ----------

def test_task_happy_path():
    t = Task("a", "x")
    t.start()
    assert t.status is TaskStatus.RUNNING and t.attempts == 1
    t.succeed("done")
    assert t.status is TaskStatus.SUCCEEDED and t.output == "done"


def test_cannot_succeed_without_starting():
    with pytest.raises(InvalidTransition):
        Task("a", "x").succeed("y")


def test_finished_task_cannot_change():
    t = Task("a", "x")
    t.start()
    t.succeed(1)
    with pytest.raises(InvalidTransition):
        t.start()


def test_failed_task_retries_until_attempts_are_used():
    t = Task("a", "x", max_attempts=2)
    t.start()
    t.fail("boom")
    assert t.can_retry
    t.retry()
    assert t.status is TaskStatus.PENDING
    t.start()
    t.fail("boom")
    assert not t.can_retry
    with pytest.raises(InvalidTransition):
        t.retry()


# ---------- Workflow validation ----------

def test_workflow_needs_at_least_one_task():
    with pytest.raises(WorkflowError):
        Workflow(goal="g", tasks=[])


def test_duplicate_task_ids_are_rejected():
    with pytest.raises(WorkflowError):
        Workflow(goal="g", tasks=[Task("a", "x"), Task("a", "y")])


def test_unknown_dependency_is_rejected():
    with pytest.raises(WorkflowError):
        Workflow(goal="g", tasks=[Task("a", "x", depends_on=("ghost",))])


def test_dependency_cycle_is_rejected():
    with pytest.raises(WorkflowError):
        Workflow(
            goal="g",
            tasks=[Task("a", "x", depends_on=("b",)), Task("b", "y", depends_on=("a",))],
        )


def test_too_many_tasks_are_rejected():
    with pytest.raises(WorkflowError):
        Workflow(goal="g", tasks=[Task(f"t{i}", "x") for i in range(MAX_TASKS + 1)])


# ---------- Ordering, failure, status ----------

def test_ready_tasks_follow_dependencies():
    wf = make()
    assert [t.id for t in wf.ready_tasks()] == ["a"]
    a = wf.get("a")
    a.start()
    a.succeed("2")
    assert [t.id for t in wf.ready_tasks()] == ["b"]


def test_failed_dependency_does_not_unlock_dependents():
    wf = make()
    a = wf.get("a")
    a.start()
    a.fail("boom")
    assert wf.ready_tasks() == []


def test_skip_dependents_is_transitive():
    wf = make()
    a = wf.get("a")
    a.start()
    a.fail("boom")
    assert wf.skip_dependents("a") == ["b", "c"]
    assert wf.get("b").status is TaskStatus.SKIPPED
    assert wf.get("c").status is TaskStatus.SKIPPED


def test_status_progresses_to_succeeded():
    wf = make()
    assert wf.refresh_status() is WorkflowStatus.PENDING
    wf.get("a").start()
    assert wf.refresh_status() is WorkflowStatus.RUNNING
    wf.get("a").succeed("1")
    for task_id in ("b", "c"):
        wf.get(task_id).start()
        wf.get(task_id).succeed("ok")
    assert wf.refresh_status() is WorkflowStatus.SUCCEEDED


def test_failure_marks_workflow_failed():
    wf = make()
    a = wf.get("a")
    a.start()
    a.fail("boom")
    wf.skip_dependents("a")
    assert wf.refresh_status() is WorkflowStatus.FAILED


# ---------- Cancellation ----------

def test_cancel_stops_unfinished_tasks():
    wf = make()
    wf.get("a").start()
    wf.cancel()
    assert all(t.status is TaskStatus.CANCELLED for t in wf.tasks)
    assert wf.status is WorkflowStatus.CANCELLED
    assert wf.refresh_status() is WorkflowStatus.CANCELLED


def test_cancel_keeps_finished_tasks():
    wf = make()
    a = wf.get("a")
    a.start()
    a.succeed("2")
    wf.cancel()
    assert a.status is TaskStatus.SUCCEEDED
    assert wf.get("b").status is TaskStatus.CANCELLED


# ---------- Persistence shape ----------

def test_dict_round_trip():
    wf = make()
    a = wf.get("a")
    a.start()
    a.succeed("2")
    wf.refresh_status()
    data = wf.to_dict()
    restored = Workflow.from_dict(json.loads(json.dumps(data)))
    assert restored.to_dict() == data
    assert restored.get("a").status is TaskStatus.SUCCEEDED
    assert restored.get("b").depends_on == ("a",)


def test_get_unknown_task_raises():
    with pytest.raises(WorkflowError):
        make().get("ghost")