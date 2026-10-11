import json

from app.tool_loop import TurnResult
from app.usage_log import SETTING_NAME, PROJECT_ROOT, get_log_path, log_turn


def make_result():
    return TurnResult(
        reply="secret reply text",
        prompt_tokens=10,
        reply_tokens=5,
        total_tokens=15,
        tool_calls=2,
        tools_used=["calculator", "write_file"],
    )


def test_writes_one_json_line_with_expected_fields(tmp_path):
    log = tmp_path / "usage.jsonl"
    assert log_turn(make_result(), source="web", path=log) is True
    lines = log.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    entry = json.loads(lines[0])
    assert entry["source"] == "web"
    assert entry["tools"] == ["calculator", "write_file"]
    assert entry["tool_calls"] == 2
    assert entry["total_tokens"] == 15
    assert entry["hit_round_limit"] is False


def test_message_text_is_never_logged(tmp_path):
    log = tmp_path / "usage.jsonl"
    log_turn(make_result(), path=log)
    assert "secret reply text" not in log.read_text(encoding="utf-8")


def test_each_turn_appends_a_new_line(tmp_path):
    log = tmp_path / "usage.jsonl"
    log_turn(make_result(), path=log)
    log_turn(make_result(), path=log)
    assert len(log.read_text(encoding="utf-8").splitlines()) == 2


def test_missing_folder_is_created(tmp_path):
    log = tmp_path / "deep" / "er" / "usage.jsonl"
    assert log_turn(make_result(), path=log) is True
    assert log.exists()


def test_write_failure_returns_false_instead_of_raising(tmp_path):
    # A folder cannot be opened as a file, so the write fails.
    assert log_turn(make_result(), path=tmp_path) is False


def test_default_path_when_nothing_is_set(tmp_path, monkeypatch):
    monkeypatch.delenv(SETTING_NAME, raising=False)
    path = get_log_path(env_file=tmp_path / "missing.env")
    assert path == PROJECT_ROOT / "logs" / "tool_usage.jsonl"


def test_setting_is_read_from_env_file(tmp_path, monkeypatch):
    monkeypatch.delenv(SETTING_NAME, raising=False)
    # tmp_path is an absolute path on both Windows and Linux.
    wanted = tmp_path / "logs" / "mine.jsonl"
    env = tmp_path / ".env"
    env.write_text(
        '# comment\nTOOL_LOG_PATH="' + wanted.as_posix() + '"\n', encoding="utf-8"
    )
    assert get_log_path(env_file=env).as_posix() == wanted.as_posix()


def test_environment_variable_beats_env_file(tmp_path, monkeypatch):
    env = tmp_path / ".env"
    env.write_text("TOOL_LOG_PATH=from_file.jsonl\n", encoding="utf-8")
    wanted = tmp_path / "from_env.jsonl"
    monkeypatch.setenv(SETTING_NAME, wanted.as_posix())
    assert get_log_path(env_file=env).as_posix() == wanted.as_posix()