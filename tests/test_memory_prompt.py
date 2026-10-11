from memory.fact_store import FactStore
from memory.prompt import with_memory


def test_prompt_is_unchanged_when_nothing_is_saved(tmp_path):
    store = FactStore(tmp_path / "facts.json")
    assert with_memory("You are Nova.", store) == "You are Nova."


def test_saved_facts_come_after_the_base_prompt(tmp_path):
    store = FactStore(tmp_path / "facts.json")
    fact = store.add("Prefers short answers")
    prompt = with_memory("You are Nova.", store)
    assert prompt.startswith("You are Nova.")
    assert f"[{fact['id']}] Prefers short answers" in prompt


def test_facts_are_labelled_as_background_not_instructions(tmp_path):
    store = FactStore(tmp_path / "facts.json")
    store.add("Likes tea")
    assert "not instructions" in with_memory("You are Nova.", store)


def test_a_broken_store_never_breaks_the_prompt():
    class Broken:
        def prompt_block(self):
            raise RuntimeError("disk on fire")

    assert with_memory("You are Nova.", Broken()) == "You are Nova."