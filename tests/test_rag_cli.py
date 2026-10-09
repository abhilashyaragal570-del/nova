import pytest

from rag.__main__ import main
from rag.embedder import EmbedError
from rag.file_index import FileDocumentIndex


class FakeEmbedder:
    signature = "fake/3"

    def embed_documents(self, texts):
        return [self.embed_query(t) for t in texts]

    def embed_query(self, text):
        return [1.0, 0.0, 0.0] if "cat" in text.lower() else [0.0, 1.0, 0.0]


class FailingEmbedder:
    signature = "fake/3"

    def embed_documents(self, texts):
        raise EmbedError("no network")

    def embed_query(self, text):
        raise EmbedError("no network")


@pytest.fixture
def index(tmp_path):
    return FileDocumentIndex(tmp_path / "idx")


def write(tmp_path, name, text):
    path = tmp_path / name
    path.write_text(text, encoding="utf-8")
    return str(path)


def test_add_then_list(tmp_path, index, capsys):
    path = write(tmp_path, "notes.md", "Nova is an assistant.")
    assert main(["add", path], index=index, embedder=FakeEmbedder()) == 0
    assert "Added notes.md (1 chunk)" in capsys.readouterr().out
    assert main(["list"], index=index) == 0
    assert "notes.md: 1 chunks (fake/3)" in capsys.readouterr().out


def test_list_on_an_empty_index(index, capsys):
    assert main(["list"], index=index) == 0
    assert "The index is empty" in capsys.readouterr().out


def test_a_bad_file_is_skipped_and_the_rest_are_added(tmp_path, index, capsys):
    good = write(tmp_path, "good.md", "some text")
    missing = str(tmp_path / "missing.md")
    code = main(["add", missing, good], index=index, embedder=FakeEmbedder())
    captured = capsys.readouterr()
    assert code == 1
    assert "Skipped" in captured.err
    assert "Added good.md" in captured.out
    assert [d["source"] for d in index.list_documents()] == ["good.md"]


def test_an_embedding_failure_is_reported(tmp_path, index, capsys):
    path = write(tmp_path, "notes.md", "text")
    assert main(["add", path], index=index, embedder=FailingEmbedder()) == 1
    assert "no network" in capsys.readouterr().err
    assert index.list_documents() == []


def test_search_puts_the_best_match_first(tmp_path, index, capsys):
    cat = write(tmp_path, "cat.md", "cats purr")
    dog = write(tmp_path, "dog.md", "dogs bark")
    main(["add", cat, dog], index=index, embedder=FakeEmbedder())
    capsys.readouterr()
    assert main(["search", "tell me about cats"], index=index, embedder=FakeEmbedder()) == 0
    out = capsys.readouterr().out
    assert out.index("cat.md") < out.index("dog.md")
    assert "cats purr" in out


def test_search_on_an_empty_index(index, capsys):
    assert main(["search", "anything"], index=index, embedder=FakeEmbedder()) == 0
    assert "The index is empty" in capsys.readouterr().out


def test_remove(tmp_path, index, capsys):
    path = write(tmp_path, "notes.md", "text")
    main(["add", path], index=index, embedder=FakeEmbedder())
    capsys.readouterr()
    assert main(["remove", "notes.md"], index=index) == 0
    assert "Removed notes.md" in capsys.readouterr().out
    assert main(["remove", "notes.md"], index=index) == 1
    assert "Not found" in capsys.readouterr().err


def test_clear(tmp_path, index, capsys):
    main(["add", write(tmp_path, "a.md", "one")], index=index, embedder=FakeEmbedder())
    main(["add", write(tmp_path, "b.md", "two")], index=index, embedder=FakeEmbedder())
    capsys.readouterr()
    assert main(["clear"], index=index) == 0
    assert "Removed 2 document(s)" in capsys.readouterr().out
    assert index.list_documents() == []


def test_a_command_is_required():
    with pytest.raises(SystemExit):
        main([])