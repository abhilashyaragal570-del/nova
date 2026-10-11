import json

from app import usage_report
from app.usage_report import format_report, read_entries, summarize


def entry(source="terminal", tools=(), tokens=100, limit=False):
    return {
        "source": source,
        "tools": list(tools),
        "tool_calls": len(tools),
        "hit_round_limit": limit,
        "total_tokens": tokens,
    }


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