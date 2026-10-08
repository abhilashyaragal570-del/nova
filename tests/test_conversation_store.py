import json
import os

import pytest

from memory.conversation_store import (
    MAIN_ID,
    MAIN_TITLE,
    NEW_TITLE,
    ConversationStore,
)

MSGS = [{"role": "user", "text": "héllo ✓"}, {"role": "model", "text": "hi"}]


@pytest.fixture
def store(tmp_path):
    return ConversationStore(tmp_path / "conversations", tmp_path / "history.json")


def test_list_starts_with_main_only(store):
    assert store.list_conversations() == [{"id": MAIN_ID, "title": MAIN_TITLE}]


def test_main_is_empty_before_anything_saved(store):
    assert store.load(MAIN_ID) == {"title": MAIN_TITLE, "messages": []}


def test_main_roundtrip_uses_history_file(store, tmp_path):
    store.save(MAIN_ID, "ignored", MSGS)
    assert store.load(MAIN_ID)["messages"] == MSGS
    saved = json.loads((tmp_path / "history.json").read_text(encoding="utf-8"))
    assert saved == MSGS


def test_create_then_load(store):
    cid = store.create()
    assert store.is_valid_id(cid)
    assert store.load(cid) == {"title": NEW_TITLE, "messages": []}


def test_save_and_load_roundtrip(store):
    cid = store.create()
    store.save(cid, "my title", MSGS)
    assert store.load(cid) == {"title": "my title", "messages": MSGS}


def test_list_is_newest_first(store):
    old, new = store.create(), store.create()
    os.utime(store.conv_dir / f"{old}.json", (1000, 1000))
    os.utime(store.conv_dir / f"{new}.json", (2000, 2000))
    ids = [c["id"] for c in store.list_conversations()]
    assert ids == [MAIN_ID, new, old]


def test_unknown_id_returns_none(store):
    assert store.load("aaaaaaaaaaaa") is None


@pytest.mark.parametrize(
    "bad", ["../x", "not-valid", "", None, "AAAAAAAAAAAA", "aaaaaaaaaaaaa"]
)
def test_invalid_ids_are_rejected(store, bad):
    assert store.is_valid_id(bad) is False
    assert store.load(bad) is None
    assert store.delete(bad) is False


def test_save_rejects_invalid_id(store):
    with pytest.raises(ValueError):
        store.save("../evil", "t", [])


def test_delete_removes_conversation(store):
    cid = store.create()
    assert store.delete(cid) is True
    assert store.load(cid) is None


def test_delete_main_removes_history_file(store, tmp_path):
    store.save(MAIN_ID, "x", MSGS)
    assert store.delete(MAIN_ID) is True
    assert not (tmp_path / "history.json").exists()
    assert store.load(MAIN_ID)["messages"] == []


def test_delete_missing_is_ok(store):
    assert store.delete("aaaaaaaaaaaa") is True


def test_corrupt_conversation_file_is_skipped(store):
    good = store.create()
    (store.conv_dir / "bbbbbbbbbbbb.json").write_text("{not json", encoding="utf-8")
    ids = [c["id"] for c in store.list_conversations()]
    assert good in ids
    assert "bbbbbbbbbbbb" not in ids


def test_corrupt_main_history_loads_empty(store, tmp_path):
    (tmp_path / "history.json").write_text("{not json", encoding="utf-8")
    assert store.load(MAIN_ID)["messages"] == []


def test_messages_without_text_are_dropped(store):
    cid = store.create()
    store.save(cid, "t", [{"role": "user", "text": "hi"}, {"role": "model", "text": ""}])
    assert store.load(cid)["messages"] == [{"role": "user", "text": "hi"}]