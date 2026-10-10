from agents.cli import agent_menu, run_agent_from_chat
from agents.definitions import AGENTS
from memory.conversation_store import ConversationStore


def make_store(tmp_path):
    return ConversationStore(
        conv_dir=tmp_path / "conversations", history_file=tmp_path / "history.json"
    )


def test_menu_lists_every_agent():
    menu = agent_menu()
    for name in AGENTS:
        assert name in menu


def test_empty_name_prints_the_menu_and_starts_nothing(tmp_path):
    out = []
    started = run_agent_from_chat("", None, make_store(tmp_path), write=out.append)
    assert started is False
    assert "researcher" in "".join(out)


def test_unknown_name_is_reported(tmp_path):
    out = []
    started = run_agent_from_chat("banana", None, make_store(tmp_path), write=out.append)
    assert started is False
    assert "unknown agent" in "".join(out)


def test_known_name_runs_the_loop_and_returns(tmp_path, monkeypatch):
    import agents.factory

    seen = {}

    def fake_new_agent_chat(client, model, spec, source, contents):
        seen["spec"] = spec.name
        return "chat", "registry"

    monkeypatch.setattr(agents.factory, "new_agent_chat", fake_new_agent_chat)

    def fake_loop(chat, registry, spec, messages=None, save=None):
        seen["loop"] = (chat, registry, spec.name, messages)
        save([{"role": "user", "text": "hi"}])

    out = []
    store = make_store(tmp_path)
    started = run_agent_from_chat(
        " Notes ", "source", store, write=out.append, chat_loop_fn=fake_loop
    )
    assert started is True
    assert seen["spec"] == "notes"
    assert seen["loop"] == ("chat", "registry", "notes", [])
    assert "Back in the main chat" in "".join(out)
    assert not (tmp_path / "history.json").exists()