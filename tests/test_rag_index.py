import os

import pytest

from rag.file_index import FileDocumentIndex
from rag.index import MAX_CHUNKS_PER_DOCUMENT, MAX_TOP_K, RagIndexError, dot, rank

URL = os.environ.get("TEST_DATABASE_URL")
TEST_TABLE = "rag_chunks_test"

X, Y, Z = [1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]


@pytest.fixture(params=["file", "postgres"])
def index(request, tmp_path):
    if request.param == "file":
        yield FileDocumentIndex(tmp_path)
        return
    if not URL:
        pytest.skip("set TEST_DATABASE_URL to run")
    import psycopg

    from rag.postgres_index import PostgresDocumentIndex

    idx = PostgresDocumentIndex(URL, table=TEST_TABLE)
    idx.clear()
    yield idx
    with psycopg.connect(URL) as conn:
        conn.execute(f"DROP TABLE IF EXISTS {TEST_TABLE}")


def add(index, source="a.md", model="m1"):
    index.add_document(source, ["first", "second"], [X, Y], model)


# ---------- both stores ----------

def test_add_and_list(index):
    add(index)
    assert index.list_documents() == [{"source": "a.md", "chunks": 2, "model": "m1"}]


def test_search_ranks_best_first(index):
    add(index)
    results = index.search(X, "m1")
    assert [r["text"] for r in results] == ["first", "second"]
    assert results[0]["score"] == pytest.approx(1.0)
    assert results[0]["source"] == "a.md" and results[0]["chunk"] == 0


def test_top_k_limits_results(index):
    add(index)
    assert len(index.search(X, "m1", top_k=1)) == 1


def test_search_covers_every_document(index):
    add(index, "a.md")
    index.add_document("b.md", ["third"], [Z], "m1")
    sources = {r["source"] for r in index.search(Z, "m1", top_k=10)}
    assert sources == {"a.md", "b.md"}


def test_adding_again_replaces_the_document(index):
    add(index)
    index.add_document("a.md", ["only"], [Z], "m1")
    assert index.list_documents()[0]["chunks"] == 1
    assert [r["text"] for r in index.search(Z, "m1", top_k=10)] == ["only"]


def test_remove(index):
    add(index)
    assert index.remove_document("a.md") is True
    assert index.remove_document("a.md") is False
    assert index.search(X, "m1") == []
    assert index.list_documents() == []


def test_clear_reports_how_many_documents(index):
    add(index, "a.md")
    add(index, "b.md")
    assert index.clear() == 2
    assert index.list_documents() == []
    assert index.clear() == 0


def test_empty_index_searches_to_nothing(index):
    assert index.search(X, "m1") == []


def test_models_are_not_mixed_when_adding(index):
    add(index, "a.md", "m1")
    with pytest.raises(RagIndexError):
        index.add_document("b.md", ["x"], [X], "m2")
    index.add_document("a.md", ["x"], [X], "m2")  # replacing the only document is fine
    assert index.list_documents()[0]["model"] == "m2"


def test_search_with_another_model_is_refused(index):
    add(index)
    with pytest.raises(RagIndexError):
        index.search(X, "m2")


@pytest.mark.parametrize(
    "source, chunks, vectors",
    [
        ("", ["a"], [X]),
        ("   ", ["a"], [X]),
        ("a.md", [], []),
        ("a.md", ["a", "b"], [X]),
        ("a.md", ["  "], [X]),
        ("a.md", ["a", "b"], [X, [1.0, 0.0]]),
        ("a.md", ["a"], [[]]),
        ("a.md", ["a"], [[float("nan"), 0.0, 0.0]]),
        ("x" * 300, ["a"], [X]),
    ],
)
def test_bad_documents_are_refused(index, source, chunks, vectors):
    with pytest.raises(RagIndexError):
        index.add_document(source, chunks, vectors, "m1")
    assert index.list_documents() == []


def test_too_many_chunks_is_refused(index):
    n = MAX_CHUNKS_PER_DOCUMENT + 1
    with pytest.raises(RagIndexError):
        index.add_document("a.md", ["t"] * n, [X] * n, "m1")


# ---------- ranking helpers ----------

def test_dot_and_rank():
    rows = [("a", 0, "x", "m", [1.0, 0.0]), ("b", 0, "y", "m", [0.0, 1.0])]
    assert dot([1.0, 2.0], [3.0, 4.0]) == 11.0
    assert rank(rows, [0.0, 1.0], "m", 1)[0]["text"] == "y"


def test_rank_clamps_top_k():
    rows = [("a", i, "t", "m", [1.0, 0.0]) for i in range(30)]
    assert len(rank(rows, [1.0, 0.0], "m", 0)) == 1
    assert len(rank(rows, [1.0, 0.0], "m", 1000)) == MAX_TOP_K


def test_rank_refuses_another_model_or_size():
    with pytest.raises(RagIndexError):
        rank([("a", 0, "x", "m", [1.0, 0.0])], [1.0, 0.0], "other", 3)
    with pytest.raises(RagIndexError):
        rank([("a", 0, "x", "m", [1.0, 0.0, 0.0])], [1.0, 0.0], "m", 3)
    with pytest.raises(RagIndexError):
        rank([], [1.0], "m", "abc")


# ---------- file store only ----------

def test_source_names_cannot_escape_the_folder(tmp_path):
    idx = FileDocumentIndex(tmp_path / "idx")
    idx.add_document("../../evil.md", ["t"], [X], "m1")
    assert not (tmp_path / "evil.md").exists()
    names = [p.name for p in (tmp_path / "idx" / "docs").iterdir()]
    assert len(names) == 1 and names[0].endswith(".json")


def test_a_damaged_file_is_skipped(tmp_path):
    idx = FileDocumentIndex(tmp_path)
    idx.add_document("a.md", ["t"], [X], "m1")
    (tmp_path / "docs" / "junk.json").write_text("{not json", encoding="utf-8")
    assert [d["source"] for d in idx.list_documents()] == ["a.md"]


def test_a_failed_write_keeps_the_old_document(tmp_path, monkeypatch):
    idx = FileDocumentIndex(tmp_path)
    idx.add_document("a.md", ["old"], [X], "m1")

    def boom(*args, **kwargs):
        raise OSError("disk full")

    with monkeypatch.context() as m:
        m.setattr("rag.file_index.os.replace", boom)
        with pytest.raises(RagIndexError):
            idx.add_document("a.md", ["new"], [X], "m1")
    assert idx.search(X, "m1")[0]["text"] == "old"
    assert [p.suffix for p in (tmp_path / "docs").iterdir()] == [".json"]