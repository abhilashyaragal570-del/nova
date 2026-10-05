import os

os.environ.setdefault("GEMINI_API_KEY", "test-key")

from app import chat


def test_load_missing_file_returns_empty(tmp_path, monkeypatch):
    monkeypatch.setattr(chat, "HISTORY_FILE", tmp_path / "history.json")
    assert chat.load_history() == []


def test_save_then_load_round_trip(tmp_path, monkeypatch):
    monkeypatch.setattr(chat, "HISTORY_FILE", tmp_path / "history.json")
    messages = [
        {"role": "user", "text": "hi"},
        {"role": "model", "text": "Hello!"},
    ]
    chat.save_history(messages)
    assert chat.load_history() == messages


def test_broken_json_returns_empty(tmp_path, monkeypatch):
    path = tmp_path / "history.json"
    path.write_text("{not valid json", encoding="utf-8")
    monkeypatch.setattr(chat, "HISTORY_FILE", path)
    assert chat.load_history() == []


def test_empty_text_entries_are_dropped(tmp_path, monkeypatch):
    monkeypatch.setattr(chat, "HISTORY_FILE", tmp_path / "history.json")
    chat.save_history([
        {"role": "user", "text": "hi"},
        {"role": "model", "text": ""},
    ])
    assert chat.load_history() == [{"role": "user", "text": "hi"}]
