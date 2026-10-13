import json

from app.usage_report import summarize, summarize_latency
from app.workflow_log import build_workflow_entry, log_workflow
from workflows.models import Task, Workflow


def make_workflow(goal="g"):
    write = Task("a", "write", "write_note", arguments={"text": "hi"})
    think = Task("b", "think")
    write.start()
    return Workflow(goal, [write, think])


def test_an_entry_describes_the_run():
    entry = build_workflow_entry(
        make_workflow(), duration_seconds=2.5, approval_wait_seconds=1.0
    )
    assert entry["source"] == "workflow"
    assert entry["tools"] == ["write_note"]
    assert entry["tool_calls"] == 1
    assert entry["tasks"] == 2
    assert entry["status"] == make_workflow().status.value
    assert entry["workflow_seconds"] == 2.5
    assert entry["approval_wait_seconds"] == 1.0
    assert "duration_seconds" not in entry


def test_the_entry_never_holds_the_goal_or_arguments():
    entry = build_workflow_entry(make_workflow("secret goal"), 1.0, 0.0)
    text = json.dumps(entry)
    assert "secret goal" not in text
    assert "hi" not in entry.get("tools", [])
    assert '"text"' not in text


def test_a_bad_time_is_not_recorded():
    for bad in ("1", True, -1, float("inf"), float("nan"), None):
        entry = build_workflow_entry(make_workflow(), bad, bad)
        assert "workflow_seconds" not in entry, bad
        assert "approval_wait_seconds" not in entry, bad


def test_log_workflow_appends_a_line(tmp_path):
    log = tmp_path / "usage.jsonl"
    assert log_workflow(make_workflow(), 3.0, 1.0, path=log) is True
    assert log_workflow(make_workflow(), 4.0, 0.0, path=log) is True
    lines = [json.loads(x) for x in log.read_text(encoding="utf-8").splitlines()]
    assert len(lines) == 2
    assert lines[0]["workflow_seconds"] == 3.0
    assert lines[1]["workflow_seconds"] == 4.0


def test_workflow_entries_do_not_count_as_chat_latency():
    entry = build_workflow_entry(make_workflow(), 120.0, 10.0)
    assert summarize_latency([entry]) is None
    assert summarize([entry])["sources"]["workflow"]["turns"] == 1