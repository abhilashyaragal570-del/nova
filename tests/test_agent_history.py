from agents.definitions import AGENTS, get_agent
from agents.history import (
    clear_messages,
    conversation_id,
    load_messages,
    save_messages,
    to_contents,
)
from memory.conversation_store import MAIN_ID, ConversationStore


def make_store(tmp_path):
    return ConversationStore(
        conv_dir=tmp_path / "conversations", history_file=tmp_path / "history.json"
    )


def test_id_is_valid_stable_and_not_main():
    cid = conversation_id("notes")
    assert ConversationStore.is_valid_id(cid)
    assert cid != MAIN_ID
    assert cid == conversation_id("notes")


def test_every_agent_has_its_own_id():
    ids = {conversation_id(name) for name in AGENTS}
    assert len(ids) == len(AGENTS)


def test_messages_round_trip(tmp_path):
    store = make_store(tmp_path)
    spec = get_agent("notes")
    assert load_messages(store, spec) == []
    messages = [{"role": "user", "text": "hi"}, {"role": "model", "text": "hello"}]
    save_messages(store, spec, messages)
    assert load_messages(store, spec) == messages


def test_clear_removes_the_saved_conversation(tmp_path):
    store = make_store(tmp_path)
    spec = get_agent("notes")
    save_messages(store, spec, [{"role": "user", "text": "hi"}])
    clear_messages(store, spec)
    assert load_messages(store, spec) == []


def test_agent_chats_never_touch_the_main_history(tmp_path):
    store = make_store(tmp_path)
    save_messages(store, get_agent("notes"), [{"role": "user", "text": "hi"}])
    assert not (tmp_path / "history.json").exists()
    assert store.load(MAIN_ID)["messages"] == []


def test_to_contents_keeps_roles_and_text():
    contents = to_contents(
        [{"role": "user", "text": "q"}, {"role": "model", "text": "a"}]
    )
    assert [c.role for c in contents] == ["user", "model"]
    assert [c.parts[0].text for c in contents] == ["q", "a"]