import json

from app import usage_report
from app.usage_report import old_log_path, read_all_entries


def entry(tool="calculator", tokens=10, source="web"):
    return {
        "source": source,
        "tools": [tool],
        "tool_calls": 1,
        "hit_round_limit": False,
        "total_tokens": tokens,
    }


def write(path, *entries):
    path.write_text(
        "".join(json.dumps(e) + "\n" for e in entries), encoding="utf-8"
    )


def test_old_log_path_is_the_dot_one_file_next_to_the_log(tmp_path):
    log = tmp_path / "usage.jsonl"
    assert old_log_path(log) == tmp_path / "usage.jsonl.1"


def test_only_the_current_file(tmp_path):
    log = tmp_path / "usage.jsonl"
    write(log, entry("a"), entry("b"))
    entries, skipped = read_all_entries(log)
    assert [e["tools"] for e in entries] == [["a"], ["b"]]
    assert skipped == 0


def test_old_file_comes_before_the_current_file(tmp_path):
    log = tmp_path / "usage.jsonl"
    write(tmp_path / "usage.jsonl.1", entry("old"))
    write(log, entry("new"))
    entries, _ = read_all_entries(log)
    assert [e["tools"] for e in entries] == [["old"], ["new"]]


def test_old_file_alone_is_still_read(tmp_path):
    log = tmp_path / "usage.jsonl"
    write(tmp_path / "usage.jsonl.1", entry("old"))
    entries, skipped = read_all_entries(log)
    assert [e["tools"] for e in entries] == [["old"]]
    assert skipped == 0


def test_no_files_gives_nothing(tmp_path):
    assert read_all_entries(tmp_path / "usage.jsonl") == ([], 0)


def test_unreadable_lines_are_counted_across_both_files(tmp_path):
    log = tmp_path / "usage.jsonl"
    (tmp_path / "usage.jsonl.1").write_text(
        json.dumps(entry("old")) + "\nnot json\n", encoding="utf-8"
    )
    log.write_text(json.dumps(entry("new")) + "\n[1, 2]\n", encoding="utf-8")
    entries, skipped = read_all_entries(log)
    assert len(entries) == 2
    assert skipped == 2


def test_report_totals_include_the_older_log(tmp_path, monkeypatch, capsys):
    log = tmp_path / "usage.jsonl"
    write(tmp_path / "usage.jsonl.1", entry("old", tokens=10))
    write(log, entry("new", tokens=5))
    monkeypatch.setattr(usage_report, "get_log_path", lambda: log)
    assert usage_report.main() == 0
    out = capsys.readouterr().out
    assert "Turns: 2" in out
    assert "Total tokens: 15" in out
    assert "includes the older log usage.jsonl.1" in out


def test_report_without_an_older_log_is_unchanged(tmp_path, monkeypatch, capsys):
    log = tmp_path / "usage.jsonl"
    write(log, entry("new", tokens=5))
    monkeypatch.setattr(usage_report, "get_log_path", lambda: log)
    assert usage_report.main() == 0
    out = capsys.readouterr().out
    assert "Turns: 1" in out
    assert "includes the older log" not in out

    empty = tmp_path / "missing" / "usage.jsonl"
    monkeypatch.setattr(usage_report, "get_log_path", lambda: empty)
    assert usage_report.main() == 1
    assert "No usage log found" in capsys.readouterr().out