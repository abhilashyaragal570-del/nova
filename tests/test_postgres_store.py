import os

import pytest
from dotenv import load_dotenv

load_dotenv()

from memory.conversation_store import MAIN_ID, MAIN_TITLE, NEW_TITLE

URL = os.environ.get("TEST_DATABASE_URL") or os.environ.get("DATABASE_URL")

pytestmark = pytest.mark.skipif(not URL, reason="no DATABASE_URL set")

MSGS = [{"role": "user", "text": "héllo ✓"}, {"role": "model", "text": "hi"}]


@pytest.fixture
def store():
    from memory.postgres_store import PostgresConversationStore
    import psycopg

    s = PostgresConversationStore(URL)
    created = []
    original_create = s.create

    def tracked_create(title=NEW_TITLE):
        cid = original_create(title)
        created.append(cid)
        return cid

    s.create = tracked_create
    yield s
    with psycopg.connect(URL) as conn:
        for cid in created:
            conn.execute("DELETE FROM conversations WHERE id = %s", (cid,))


def test_create_then_load(store):
    cid = store.create()
    assert store.is_valid_id(cid)
    assert store.load(cid) == {"title": NEW_TITLE, "messages": []}


def test_save_and_load_roundtrip(store):
    cid = store.create()
    store.save(cid, "my title", MSGS)
    assert store.load(cid) == {"title": "my title", "messages": MSGS}


def test_unknown_id_returns_none(store):
    assert store.load("aaaaaaaaaaaa") is None


@pytest.mark.parametrize("bad", ["../x", "not-valid", "", None, "AAAAAAAAAAAA"])
def test_invalid_ids_are_rejected(store, bad):
    assert store.load(bad) is None
    assert store.delete(bad) is False


def test_save_rejects_invalid_id(store):
    with pytest.raises(ValueError):
        store.save("../evil", "t", [])


def test_delete_removes_conversation(store):
    cid = store.create()
    assert store.delete(cid) is True
    assert store.load(cid) is None


def test_delete_missing_is_ok(store):
    assert store.delete("aaaaaaaaaaaa") is True


def test_messages_without_text_are_dropped(store):
    cid = store.create()
    store.save(cid, "t", [{"role": "user", "text": "hi"}, {"role": "model", "text": ""}])
    assert store.load(cid)["messages"] == [{"role": "user", "text": "hi"}]


def test_list_has_main_first_and_new_chat(store):
    cid = store.create("listed")
    items = store.list_conversations()
    assert items[0] == {"id": MAIN_ID, "title": MAIN_TITLE}
    assert {"id": cid, "title": "listed"} in items