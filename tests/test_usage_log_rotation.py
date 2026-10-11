import json

from app.tool_loop import TurnResult
from app.usage_log import log_turn


def make_result(name="calculator"):
    return TurnResult(tool_calls=1, tools_used=[name], total_tokens=10)


def lines(path):
    return path.read_text(encoding="utf-8").splitlines()


def test_small_log_is_not_rotated(tmp_path):
    log = tmp_path / "usage.jsonl"
    log_turn(make_result(), path=log)
    log_turn(make_result(), path=log)
    assert len(lines(log)) == 2
    assert not (tmp_path / "usage.jsonl.1").exists()


def test_full_log_moves_to_dot_one_and_a_fresh_log_starts(tmp_path):
    log = tmp_path / "usage.jsonl"
    log_turn(make_result("first"), path=log, max_bytes=50)
    log_turn(make_result("second"), path=log, max_bytes=50)
    backup = tmp_path / "usage.jsonl.1"
    assert json.loads(lines(backup)[0])["tools"] == ["first"]
    assert len(lines(log)) == 1
    assert json.loads(lines(log)[0])["tools"] == ["second"]


def test_only_one_old_file_is_kept(tmp_path):
    log = tmp_path / "usage.jsonl"
    for name in ("first", "second", "third"):
        log_turn(make_result(name), path=log, max_bytes=50)
    backup = tmp_path / "usage.jsonl.1"
    assert len(lines(backup)) == 1
    assert json.loads(lines(backup)[0])["tools"] == ["second"]
    assert json.loads(lines(log)[0])["tools"] == ["third"]
    assert not (tmp_path / "usage.jsonl.2").exists()


def test_rotation_still_returns_true(tmp_path):
    log = tmp_path / "usage.jsonl"
    log_turn(make_result(), path=log, max_bytes=50)
    assert log_turn(make_result(), path=log, max_bytes=50) is True