import os

import pytest

from workflows.models import Task, TaskStatus, Workflow, WorkflowStatus
from workflows.store import StoreError

URL = os.environ.get("TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(not URL, reason="set TEST_DATABASE_URL to run")


@pytest.fixture
def store():
    from workflows.postgres_store import PostgresWorkflowStore

    s = PostgresWorkflowStore(URL)
    yield s
    import psycopg

    with psycopg.connect(URL) as conn:
        conn.execute("DELETE FROM workflow_runs WHERE id LIKE 'pgtest%'")
        conn.execute("DELETE FROM workflow_events WHERE workflow_id LIKE 'pgtest%'")


def make():
    return Workflow(
        goal="g",
        tasks=[Task("a", "x", "echo"), Task("b", "y", "echo", depends_on=("a",))],
        id="pgtest1",
    )


def test_round_trip(store):
    wf = make()
    a = wf.get("a")
    a.start()
    a.succeed("result")
    store.save(wf)
    assert store.load("pgtest1").to_dict() == wf.to_dict()


def test_save_overwrites(store):
    wf = make()
    store.save(wf)
    wf.get("a").start()
    store.save(wf)
    assert store.load("pgtest1", resume=False).get("a").status is TaskStatus.RUNNING


def test_unserializable_is_refused_and_old_row_survives(store):
    wf = make()
    store.save(wf)
    a = wf.get("a")
    a.start()
    a.succeed(object())
    with pytest.raises(StoreError):
        store.save(wf)
    assert store.load("pgtest1").get("a").status is TaskStatus.PENDING


@pytest.mark.parametrize("bad", ["", "..", "a/b", "x" * 100, None, 5])
def test_bad_ids_are_rejected(store, bad):
    with pytest.raises(StoreError):
        store.load(bad)
    with pytest.raises(StoreError):
        store.append_event(bad, "start", "a")


def test_missing_workflow(store):
    with pytest.raises(StoreError):
        store.load("pgtest-missing")


def test_resume_resets_running_tasks(store):
    wf = make()
    wf.get("a").start()
    wf.refresh_status()
    store.save(wf)
    loaded = store.load("pgtest1")
    assert loaded.get("a").status is TaskStatus.PENDING
    assert loaded.get("a").attempts == 0
    assert loaded.status is WorkflowStatus.PENDING


def test_list_ids(store):
    store.save(make())
    assert "pgtest1" in store.list_ids()


def test_event_log_round_trip(store):
    store.append_event("pgtest1", "start", "a", "attempt 1/1")
    store.append_event("pgtest1", "succeed", "a")
    events = store.read_events("pgtest1")
    assert [e["kind"] for e in events] == ["start", "succeed"]
    assert events[0]["detail"] == "attempt 1/1"
    assert events[0]["ts"] > 0


def test_read_events_without_log_is_empty(store):
    assert store.read_events("pgtest-none") == []