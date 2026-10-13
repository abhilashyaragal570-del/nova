from pathlib import Path

from memory.conversation_store import ConversationStore
from memory.state_dir import state_path

MESSAGES = [{"role": "user", "text": "hello"}]


def test_state_path_without_the_variable_is_the_plain_file_name(monkeypatch):
    monkeypatch.delenv("NOVA_STATE_DIR", raising=False)
    assert state_path("history.json") == Path("history.json")


def test_an_empty_variable_counts_as_not_set(monkeypatch):
    monkeypatch.setenv("NOVA_STATE_DIR", "   ")
    assert state_path("history.json") == Path("history.json")


def test_state_path_uses_the_folder(monkeypatch, tmp_path):
    monkeypatch.setenv("NOVA_STATE_DIR", str(tmp_path / "state"))
    assert state_path("personality.json") == tmp_path / "state" / "personality.json"


def test_main_chat_goes_to_the_state_folder(monkeypatch, tmp_path):
    monkeypatch.setenv("NOVA_STATE_DIR", str(tmp_path / "state"))
    store = ConversationStore(conv_dir=tmp_path / "conversations")
    # The folder does not exist yet, so saving has to create it.
    store.save("main", "Main chat", MESSAGES)
    assert (tmp_path / "state" / "history.json").exists()
    assert store.load("main")["messages"] == MESSAGES


def test_main_chat_stays_in_the_current_folder_without_the_variable(
    monkeypatch, tmp_path
):
    monkeypatch.delenv("NOVA_STATE_DIR", raising=False)
    monkeypatch.chdir(tmp_path)
    store = ConversationStore(conv_dir=tmp_path / "conversations")
    store.save("main", "Main chat", MESSAGES)
    assert (tmp_path / "history.json").exists()
    assert store.load("main")["messages"] == MESSAGES


def test_an_explicit_history_file_wins_over_the_variable(monkeypatch, tmp_path):
    monkeypatch.setenv("NOVA_STATE_DIR", str(tmp_path / "state"))
    store = ConversationStore(
        conv_dir=tmp_path / "conversations", history_file=tmp_path / "mine.json"
    )
    store.save("main", "Main chat", MESSAGES)
    assert (tmp_path / "mine.json").exists()
    assert not (tmp_path / "state").exists()