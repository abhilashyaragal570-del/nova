from memory.fact_store import FactStore
from tools.memory_tools import ForgetTool, ListMemoriesTool, RememberTool
from tools.policy import ToolPolicy


def make_store(tmp_path, **kwargs):
    return FactStore(tmp_path / "facts.json", **kwargs)


def test_remember_saves_a_fact(tmp_path):
    store = make_store(tmp_path)
    result = RememberTool(store).run(fact="Prefers short answers")
    assert result.ok is True
    assert result.output["saved"] == "Prefers short answers"
    assert [f["text"] for f in store.list()] == ["Prefers short answers"]
    assert result.output["id"] == store.list()[0]["id"]


def test_remember_rejects_empty_fact(tmp_path):
    store = make_store(tmp_path)
    result = RememberTool(store).run(fact="   ")
    assert result.ok is False
    assert store.list() == []


def test_remember_reports_full_memory(tmp_path):
    store = make_store(tmp_path, max_facts=1)
    tool = RememberTool(store)
    assert tool.run(fact="one").ok is True
    result = tool.run(fact="two")
    assert result.ok is False
    assert "full" in result.error


def test_remember_same_fact_twice_keeps_one(tmp_path):
    store = make_store(tmp_path)
    tool = RememberTool(store)
    first = tool.run(fact="Likes tea")
    second = tool.run(fact="likes tea")
    assert second.ok is True
    assert second.output["id"] == first.output["id"]
    assert len(store.list()) == 1


def test_forget_removes_a_fact(tmp_path):
    store = make_store(tmp_path)
    fact = store.add("Likes tea")
    result = ForgetTool(store).run(fact_id=fact["id"])
    assert result.ok is True
    assert result.output == {"forgotten": fact["id"]}
    assert store.list() == []


def test_forget_unknown_id_fails(tmp_path):
    store = make_store(tmp_path)
    store.add("keep me")
    result = ForgetTool(store).run(fact_id="nope")
    assert result.ok is False
    assert len(store.list()) == 1


def test_list_memories_returns_ids_and_texts(tmp_path):
    store = make_store(tmp_path)
    fact = store.add("Likes tea")
    result = ListMemoriesTool(store).run()
    assert result.ok is True
    assert result.output == [{"id": fact["id"], "text": "Likes tea"}]


def test_list_memories_when_empty(tmp_path):
    result = ListMemoriesTool(make_store(tmp_path)).run()
    assert result.ok is True
    assert result.output == []


def test_only_list_memories_is_read_only(tmp_path):
    store = make_store(tmp_path)
    assert RememberTool(store).read_only is False
    assert ForgetTool(store).read_only is False
    assert ListMemoriesTool(store).read_only is True


def test_remember_and_forget_need_approval(tmp_path):
    store = make_store(tmp_path)
    for tool, args in (
        (RememberTool(store), {"fact": "x"}),
        (ForgetTool(store), {"fact_id": "abc"}),
    ):
        none_configured = ToolPolicy().check(tool, args)
        assert none_configured and "confirmation" in none_configured
        assert ToolPolicy(confirm=lambda n, a: False).check(tool, args) is not None
        assert ToolPolicy(confirm=lambda n, a: True).check(tool, args) is None


def test_list_memories_needs_no_approval(tmp_path):
    tool = ListMemoriesTool(make_store(tmp_path))
    assert ToolPolicy().check(tool, {}) is None


def test_names_are_distinct_and_schemas_require_the_right_fields(tmp_path):
    store = make_store(tmp_path)
    remember, forget, listing = RememberTool(store), ForgetTool(store), ListMemoriesTool(store)
    assert {remember.name, forget.name, listing.name} == {
        "remember",
        "forget",
        "list_memories",
    }
    assert remember.parameters["required"] == ["fact"]
    assert forget.parameters["required"] == ["fact_id"]
    assert listing.parameters["required"] == []