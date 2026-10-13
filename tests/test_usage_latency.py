import json
from types import SimpleNamespace

from fastapi.testclient import TestClient

from app import usage_report
from app.usage_log import build_entry, log_turn
from app.usage_report import format_latency, percentile, summarize_latency
from web import fastapi_app

PASSWORD = "test-password"
AUTH = ("user", PASSWORD)


def turn():
    return SimpleNamespace(
        tools_used=["calculator"],
        tool_calls=1,
        hit_round_limit=False,
        prompt_tokens=1,
        reply_tokens=2,
        total_tokens=3,
    )


def timed(seconds, source="web", wait=None):
    entry = {
        "source": source,
        "tools": [],
        "tool_calls": 0,
        "hit_round_limit": False,
        "total_tokens": 10,
        "duration_seconds": seconds,
    }
    if wait is not None:
        entry["approval_wait_seconds"] = wait
    return entry


def write(path, *entries):
    path.write_text("".join(json.dumps(e) + "\n" for e in entries), encoding="utf-8")


def test_an_entry_has_no_duration_when_none_is_given():
    entry = build_entry(turn(), "web")
    assert "duration_seconds" not in entry
    assert "approval_wait_seconds" not in entry


def test_an_entry_records_the_duration():
    entry = build_entry(turn(), "web", duration_seconds=1.23456)
    assert entry["duration_seconds"] == 1.235


def test_log_turn_writes_the_duration_and_the_wait(tmp_path):
    log = tmp_path / "usage.jsonl"
    assert (
        log_turn(
            turn(),
            source="web",
            path=log,
            duration_seconds=2.5,
            approval_wait_seconds=1.0,
        )
        is True
    )
    line = json.loads(log.read_text(encoding="utf-8").splitlines()[0])
    assert line["duration_seconds"] == 2.5
    assert line["approval_wait_seconds"] == 1.0
    assert line["source"] == "web"


def test_a_bad_duration_is_not_recorded():
    for bad in ("1", True, -1, float("inf"), float("nan"), None):
        entry = build_entry(turn(), "web", duration_seconds=bad)
        assert "duration_seconds" not in entry, bad


def test_percentile_uses_the_nearest_rank():
    ten = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10]
    assert percentile(ten, 50) == 5
    assert percentile(ten, 95) == 10
    assert percentile([7], 95) == 7
    assert percentile([], 95) is None


def test_latency_is_none_without_durations():
    assert summarize_latency([]) is None
    assert summarize_latency([{"source": "web", "tools": []}]) is None


def test_latency_summary():
    entries = [timed(s) for s in (1, 2, 3, 4, 5)]
    entries.append({"source": "terminal", "tools": []})
    assert summarize_latency(entries) == {
        "turns": 5,
        "average_seconds": 3.0,
        "median_seconds": 3.0,
        "p95_seconds": 5.0,
        "max_seconds": 5.0,
        "approval_wait_seconds": 0.0,
        "turns_with_approval": 0,
    }


def test_latency_ignores_entries_without_a_usable_duration():
    entries = [
        timed("fast"),
        timed(True),
        timed(-1),
        timed(None),
        timed(float("nan")),
        timed(2.0),
    ]
    latency = summarize_latency(entries)
    assert latency["turns"] == 1
    assert latency["average_seconds"] == 2.0


def test_format_latency():
    text = format_latency(summarize_latency([timed(s) for s in (1, 2, 3, 4, 5)]))
    assert "Latency (5 timed turns):" in text
    assert "average  3.00s" in text
    assert "95th     5.00s" in text
    assert "slowest  5.00s" in text
    assert "approval" not in text


def test_report_prints_latency_when_there_is_any(tmp_path, monkeypatch, capsys):
    log = tmp_path / "usage.jsonl"
    write(log, timed(1.0), timed(3.0))
    monkeypatch.setattr(usage_report, "get_log_path", lambda: log)
    assert usage_report.main() == 0
    out = capsys.readouterr().out
    assert "Turns: 2" in out
    assert "Latency (2 timed turns):" in out
    assert "95th" in out


def test_report_without_durations_has_no_latency_section(tmp_path, monkeypatch, capsys):
    log = tmp_path / "usage.jsonl"
    write(log, {"source": "web", "tools": [], "total_tokens": 5})
    monkeypatch.setattr(usage_report, "get_log_path", lambda: log)
    assert usage_report.main() == 0
    out = capsys.readouterr().out
    assert "Turns: 1" in out
    assert "Latency" not in out


def test_usage_api_includes_latency(monkeypatch, tmp_path):
    monkeypatch.setenv("NOVA_PASSWORD", PASSWORD)
    log = tmp_path / "usage.jsonl"
    write(log, timed(1.0), timed(3.0))
    monkeypatch.setenv("TOOL_LOG_PATH", str(log))
    data = TestClient(fastapi_app.app).get("/api/usage", auth=AUTH).json()
    assert data["turns"] == 2
    assert data["latency"]["turns"] == 2
    assert data["latency"]["average_seconds"] == 2.0
    assert data["latency"]["max_seconds"] == 3.0


def test_usage_api_latency_is_null_without_durations(monkeypatch, tmp_path):
    monkeypatch.setenv("NOVA_PASSWORD", PASSWORD)
    log = tmp_path / "usage.jsonl"
    write(log, {"source": "web", "tools": [], "total_tokens": 5})
    monkeypatch.setenv("TOOL_LOG_PATH", str(log))
    data = TestClient(fastapi_app.app).get("/api/usage", auth=AUTH).json()
    assert data["turns"] == 1
    assert data["latency"] is None


def test_an_entry_records_the_approval_wait():
    entry = build_entry(
        turn(), "web", duration_seconds=3, approval_wait_seconds=1.23456
    )
    assert entry["duration_seconds"] == 3.0
    assert entry["approval_wait_seconds"] == 1.235


def test_a_bad_approval_wait_is_not_recorded():
    for bad in ("1", True, -1, float("inf"), float("nan"), None):
        entry = build_entry(
            turn(), "web", duration_seconds=3, approval_wait_seconds=bad
        )
        assert "approval_wait_seconds" not in entry, bad


def test_latency_leaves_out_the_approval_wait():
    entries = [timed(10.0, wait=8.0), timed(4.0, wait=0.0), timed(5.0)]
    latency = summarize_latency(entries)
    assert latency["turns"] == 3
    # The turns took 2s, 4s and 5s without the wait.
    assert latency["average_seconds"] == round(11 / 3, 3)
    assert latency["median_seconds"] == 4.0
    assert latency["max_seconds"] == 5.0
    assert latency["approval_wait_seconds"] == 8.0
    assert latency["turns_with_approval"] == 1


def test_latency_never_goes_below_zero():
    latency = summarize_latency([timed(1.0, wait=5.0)])
    assert latency["average_seconds"] == 0.0
    assert latency["max_seconds"] == 0.0
    assert latency["turns_with_approval"] == 1


def test_format_latency_mentions_the_approval_wait():
    text = format_latency(summarize_latency([timed(10.0, wait=8.0), timed(4.0)]))
    assert "waiting for approval in 1 turns" in text
    assert "8.00s" in text