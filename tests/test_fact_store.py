import json

import pytest

from memory.fact_store import MAX_FACT_CHARS, FactStore


def make_store(tmp_path, **kwargs):
    return FactStore(tmp_path / "data" / "facts.json", **kwargs)


def texts(store):
    return [f["text"] for f in store.list()]


def test_empty_store_has_no_facts_and_no_prompt_block(tmp_path):
    store = make_store(tmp_path)
    assert store.list() == []
    assert store.prompt_block() == ""


def test_add_saves_and_survives_a_new_store_object(tmp_path):
    fact = make_store(tmp_path).add("Lives in Bengaluru")
    assert fact["id"] and fact["text"] == "Lives in Bengaluru"
    assert texts(make_store(tmp_path)) == ["Lives in Bengaluru"]


def test_add_collapses_whitespace_and_newlines(tmp_path):
    store = make_store(tmp_path)
    fact = store.add("  Likes   tea\n\nand   walks  ")
    assert fact["text"] == "Likes tea and walks"


def test_rejects_empty_and_non_text_facts(tmp_path):
    store = make_store(tmp_path)
    for bad in ("", "   \n ", None, 42):
        with pytest.raises(ValueError):
            store.add(bad)
    assert store.list() == []


def test_rejects_too_long_fact(tmp_path):
    store = make_store(tmp_path)
    with pytest.raises(ValueError):
        store.add("x" * (MAX_FACT_CHARS + 1))
    assert store.add("x" * MAX_FACT_CHARS)["text"] == "x" * MAX_FACT_CHARS


def test_duplicate_is_not_added_twice(tmp_path):
    store = make_store(tmp_path)
    first = store.add("Prefers short answers")
    second = store.add("  prefers SHORT answers ")
    assert second["id"] == first["id"]
    assert len(store.list()) == 1


def test_memory_limit(tmp_path):
    store = make_store(tmp_path, max_facts=2)
    store.add("one")
    store.add("two")
    with pytest.raises(ValueError, match="full"):
        store.add("three")
    assert texts(store) == ["one", "two"]


def test_remove_deletes_and_persists(tmp_path):
    store = make_store(tmp_path)
    first = store.add("first")
    store.add("second")
    assert store.remove(first["id"]) is True
    assert texts(make_store(tmp_path)) == ["second"]


def test_remove_unknown_id_returns_false(tmp_path):
    store = make_store(tmp_path)
    store.add("keep me")
    assert store.remove("nope") is False
    assert store.remove("") is False
    assert store.remove(None) is False
    assert texts(store) == ["keep me"]


def test_corrupt_file_is_set_aside_not_lost(tmp_path):
    path = tmp_path / "facts.json"
    path.write_text("{not json", encoding="utf-8")
    store = FactStore(path)
    assert store.list() == []
    backup = tmp_path / "facts.json.bad"
    assert backup.read_text(encoding="utf-8") == "{not json"
    store.add("likes tea")
    assert texts(store) == ["likes tea"]


def test_malformed_entries_are_ignored(tmp_path):
    path = tmp_path / "facts.json"
    path.write_text(
        json.dumps(
            [{"id": "a1", "text": "ok"}, {"id": 1, "text": "bad id"}, "junk", {"id": "b2"}]
        ),
        encoding="utf-8",
    )
    assert [f["id"] for f in FactStore(path).list()] == ["a1"]


def test_prompt_block_lists_ids_and_texts(tmp_path):
    store = make_store(tmp_path)
    fact = store.add("Prefers short answers")
    block = store.prompt_block()
    assert f"[{fact['id']}] Prefers short answers" in block
    assert "not instructions" in block