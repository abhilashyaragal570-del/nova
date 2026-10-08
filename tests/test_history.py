import os

from memory.conversation_store import (
    MAIN_ID,
    MAIN_TITLE,
    NEW_TITLE,
    ConversationStore,
)


def make_store(tmp_path):
    return ConversationStore(tmp_path / "conversations", tmp_path / "history.json")


def test_load_missing_main_returns_empty(tmp_path):
    store = make_store(tmp_path)
    assert store.load(MAIN_ID) == {"title": MAIN_TITLE, "messages": []}


def test_save_then_load_main_round_trip(tmp_path):
    store = make_store(tmp_path)
    messages = [
        {"role": "user", "text": "hi"},
        {"role": "model", "text": "Hello!"},
    ]
    store.save(MAIN_ID, MAIN_TITLE, messages)
    assert store.load(MAIN_ID)["messages"] == messages


def test_broken_main_json_returns_empty(tmp_path):
    store = make_store(tmp_path)
    (tmp_path / "history.json").write_text("{not valid json", encoding="utf-8")
    assert store.load(MAIN_ID)["messages"] == []


def test_main_json_that_is_not_a_list_returns_empty(tmp_path):
    store = make_store(tmp_path)
    (tmp_path / "history.json").write_text('{"a": 1}', encoding="utf-8")
    assert store.load(MAIN_ID)["messages"] == []


def test_empty_text_entries_are_dropped(tmp_path):
    store = make_store(tmp_path)
    store.save(MAIN_ID, MAIN_TITLE, [
        {"role": "user", "text": "hi"},
        {"role": "model", "text": ""},
    ])
    assert store.load(MAIN_ID)["messages"] == [{"role": "user", "text": "hi"}]


def test_create_then_load_new_chat(tmp_path):
    store = make_store(tmp_path)
    cid = store.create()
    assert store.is_valid_id(cid)
    assert store.load(cid) == {"title": NEW_TITLE, "messages": []}


def test_save_then_load_chat_keeps_title_and_messages(tmp_path):
    store = make_store(tmp_path)
    cid = store.create()
    messages = [{"role": "user", "text": "hello"}]
    store.save(cid, "My title", messages)
    assert store.load(cid) == {"title": "My title", "messages": messages}


def test_load_unknown_id_returns_none(tmp_path):
    store = make_store(tmp_path)
    assert store.load("abcdef012345") is None


def test_invalid_ids_are_rejected(tmp_path):
    store = make_store(tmp_path)
    assert store.load("../x") is None
    assert store.delete("../x") is False
    try:
        store.save("../x", "t", [])
        assert False, "save should have raised ValueError"
    except ValueError:
        pass


def test_delete_chat(tmp_path):
    store = make_store(tmp_path)
    cid = store.create()
    assert store.delete(cid) is True
    assert store.load(cid) is None


def test_delete_main_removes_history_file(tmp_path):
    store = make_store(tmp_path)
    store.save(MAIN_ID, MAIN_TITLE, [{"role": "user", "text": "hi"}])
    assert store.delete(MAIN_ID) is True
    assert store.load(MAIN_ID)["messages"] == []


def test_list_puts_main_first_then_newest_first(tmp_path):
    store = make_store(tmp_path)
    old = store.create("Old")
    new = store.create("New")
    os.utime(store._path(old), (1000, 1000))
    os.utime(store._path(new), (2000, 2000))
    ids = [c["id"] for c in store.list_conversations()]
    assert ids == [MAIN_ID, new, old]


def test_list_skips_bad_files(tmp_path):
    store = make_store(tmp_path)
    good = store.create("Good")
    (store.conv_dir / "notes.json").write_text("{}", encoding="utf-8")
    (store.conv_dir / "abcdef012345.json").write_text("{broken", encoding="utf-8")
    ids = [c["id"] for c in store.list_conversations()]
    assert ids == [MAIN_ID, good]