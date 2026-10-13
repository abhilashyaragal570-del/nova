import json

from app import usage_report
from app.usage_report import (
    format_report,
    format_workflows,
    read_entries,
    summarize,
    summarize_latency,
    summarize_workflows,
)


def entry(source="terminal", tools=(), tokens=100, limit=False):
    return {
        "source": source,
        "tools": list(tools),
        "tool_calls": len(tools),
        "hit_round_limit": limit,
        "total_tokens": tokens,
    }


def workflow_entry(
    status="completed", tools=(), tasks=2, tool_calls=None, seconds=10.0, wait=None
):
    """A log line like the one app/workflow_log.py writes."""
    line = {
        "source": "workflow",
        "tools": list(tools),
        "tool_calls": len(tools) if tool_calls is None else tool_calls,
        "hit_round_limit": False,
        "total_tokens": 0,
        "tasks": tasks,
        "status": status,
    }
    if seconds is not None:
        line["workflow_seconds"] = seconds
    if wait is not None:
        line["approval_wait_seconds"] = wait
    return line


def test_read_entries_skips_bad_lines(tmp_path):
    log = tmp_path / "usage.jsonl"
    good = json.dumps(entry(tools=["calculator"]))
    log.write_text(good + "\nnot json at all\n\n[1, 2]\n" + good + "\n", encoding="utf-8")
    entries, skipped = read_entries(log)
    assert len(entries) == 2
    assert skipped == 2


def test_read_entries_missing_file_returns_empty(tmp_path):
    assert read_entries(tmp_path / "nope.jsonl") == ([], 0)


def test_summarize_counts_tools_and_tokens():
    summary = summarize(
        [
            entry(tools=["calculator", "web_search"], tokens=100),
            entry(tools=["calculator"], tokens=50),
            entry(tools=[], tokens=10, limit=True),
        ]
    )
    assert summary["turns"] == 3
    assert summary["total_tokens"] == 160
    assert summary["no_tool_turns"] == 1
    assert summary["limit_hits"] == 1
    assert summary["tools"] == {"calculator": 2, "web_search": 1}


def test_summarize_groups_by_source():
    summary = summarize(
        [
            entry(source="web", tokens=100),
            entry(source="web", tokens=200),
            entry(source="terminal", tokens=5),
        ]
    )
    assert summary["sources"]["web"] == {"turns": 2, "tokens": 300}
    assert summary["sources"]["terminal"] == {"turns": 1, "tokens": 5}


def test_summarize_empty_log():
    summary = summarize([])
    assert summary["turns"] == 0
    assert summary["tools"] == {}
    assert summary["sources"] == {}


def test_format_report_lists_tools_and_sources():
    text = format_report(
        summarize([entry(source="web", tools=["calculator"], tokens=1234)]),
        skipped=1,
    )
    assert "Turns: 1" in text
    assert "Total tokens: 1,234" in text
    assert "calculator" in text
    assert "web" in text
    assert "skipped: 1" in text


def test_main_reports_a_missing_log(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(usage_report, "get_log_path", lambda: tmp_path / "nope.jsonl")
    assert usage_report.main() == 1
    assert "No usage log found" in capsys.readouterr().out


# ---------- workflows ----------


def test_summarize_workflows_is_none_without_workflow_lines():
    assert summarize_workflows([]) is None
    assert summarize_workflows([entry(source="web"), entry(source="terminal")]) is None


def test_summarize_workflows_counts_statuses():
    result = summarize_workflows(
        [
            workflow_entry(status="completed"),
            workflow_entry(status="completed"),
            workflow_entry(status="failed"),
        ]
    )
    assert result["runs"] == 3
    assert result["statuses"] == {"completed": 2, "failed": 1}


def test_summarize_workflows_adds_up_tasks_calls_and_tools():
    result = summarize_workflows(
        [
            workflow_entry(tools=["web_search", "write_file"], tasks=3),
            workflow_entry(tools=["web_search"], tasks=2),
        ]
    )
    assert result["tasks"] == 5
    assert result["tool_calls"] == 3
    assert result["tools"] == {"web_search": 2, "write_file": 1}


def test_summarize_workflows_times_leave_out_the_approval_wait():
    result = summarize_workflows(
        [
            workflow_entry(seconds=10.0, wait=4.0),
            workflow_entry(seconds=20.0),
        ]
    )
    assert result["timed_runs"] == 2
    assert result["average_seconds"] == 13.0
    assert result["median_seconds"] == 13.0
    assert result["max_seconds"] == 20.0
    assert result["approval_wait_seconds"] == 4.0
    assert result["runs_with_approval"] == 1


def test_summarize_workflows_active_time_never_goes_below_zero():
    result = summarize_workflows([workflow_entry(seconds=5.0, wait=8.0)])
    assert result["average_seconds"] == 0.0
    assert result["max_seconds"] == 0.0
    assert result["approval_wait_seconds"] == 8.0


def test_summarize_workflows_untimed_runs_still_count_elsewhere():
    only_untimed = summarize_workflows([workflow_entry(seconds=None, tasks=4)])
    assert only_untimed["runs"] == 1
    assert only_untimed["tasks"] == 4
    assert only_untimed["timed_runs"] == 0
    assert only_untimed["average_seconds"] is None
    assert only_untimed["median_seconds"] is None
    assert only_untimed["max_seconds"] is None
    assert only_untimed["runs_with_approval"] == 0

    mixed = summarize_workflows(
        [workflow_entry(seconds=None), workflow_entry(seconds=6.0)]
    )
    assert mixed["runs"] == 2
    assert mixed["timed_runs"] == 1
    assert mixed["average_seconds"] == 6.0


def test_summarize_workflows_ignores_bad_values():
    bad = {
        "source": "workflow",
        "status": 5,
        "tools": ["write_file", 7, None],
        "tasks": "3",
        "tool_calls": True,
        "workflow_seconds": float("nan"),
        "approval_wait_seconds": "x",
    }
    negative = workflow_entry(tasks=-2, tool_calls=-1, seconds=-3.0)
    result = summarize_workflows([bad, negative])
    assert result["runs"] == 2
    assert result["statuses"] == {"unknown": 1, "completed": 1}
    assert result["tools"] == {"write_file": 1}
    assert result["tasks"] == 0
    assert result["tool_calls"] == 0
    assert result["timed_runs"] == 0


def test_summarize_workflows_unusable_wait_counts_as_zero():
    result = summarize_workflows([workflow_entry(seconds=7.0, wait=-3.0)])
    assert result["average_seconds"] == 7.0
    assert result["approval_wait_seconds"] == 0.0
    assert result["runs_with_approval"] == 0


def test_chat_and_workflow_numbers_stay_apart():
    chat = entry(source="web", tokens=50)
    chat["duration_seconds"] = 2.0
    run = workflow_entry(seconds=100.0)
    entries = [chat, run]

    workflows = summarize_workflows(entries)
    assert workflows["runs"] == 1
    assert workflows["max_seconds"] == 100.0

    latency = summarize_latency(entries)
    assert latency["turns"] == 1
    assert latency["max_seconds"] == 2.0


def test_format_workflows_shows_statuses_and_times():
    text = format_workflows(
        summarize_workflows(
            [
                workflow_entry(status="completed", seconds=10.0, wait=4.0),
                workflow_entry(status="failed", seconds=20.0),
            ]
        )
    )
    assert "Workflows (2 runs):" in text
    assert "completed" in text
    assert "failed" in text
    assert "average" in text
    assert "median" in text
    assert "slowest" in text
    assert "left out" in text


def test_format_workflows_without_timed_runs():
    text = format_workflows(summarize_workflows([workflow_entry(seconds=None)]))
    assert "Workflows (1 runs):" in text
    assert "(no timed runs)" in text
    assert "average" not in text


def test_main_prints_the_workflows_block(tmp_path, monkeypatch, capsys):
    log = tmp_path / "usage.jsonl"
    lines = [json.dumps(entry(source="web")), json.dumps(workflow_entry())]
    log.write_text("\n".join(lines) + "\n", encoding="utf-8")
    monkeypatch.setattr(usage_report, "get_log_path", lambda: log)
    assert usage_report.main() == 0
    assert "Workflows (1 runs):" in capsys.readouterr().out


def test_main_leaves_out_workflows_when_there_are_none(tmp_path, monkeypatch, capsys):
    log = tmp_path / "usage.jsonl"
    log.write_text(json.dumps(entry(source="web")) + "\n", encoding="utf-8")
    monkeypatch.setattr(usage_report, "get_log_path", lambda: log)
    assert usage_report.main() == 0
    assert "Workflows" not in capsys.readouterr().out