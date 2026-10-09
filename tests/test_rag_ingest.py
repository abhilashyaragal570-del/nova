import pytest

from rag.embedder import EmbedError
from rag.file_index import FileDocumentIndex
from rag.ingest import MAX_FILE_BYTES, IngestError, add_file


class FakeEmbedder:
    signature = "fake/3"

    def embed_documents(self, texts):
        return [[1.0, 0.0, 0.0] for _ in texts]


class FailingEmbedder:
    signature = "fake/3"

    def embed_documents(self, texts):
        raise EmbedError("no network")


@pytest.fixture
def index(tmp_path):
    return FileDocumentIndex(tmp_path / "idx")


def write(tmp_path, name, text):
    path = tmp_path / name
    path.write_text(text, encoding="utf-8")
    return path


def test_a_file_is_chunked_embedded_and_stored(tmp_path, index):
    path = write(tmp_path, "notes.md", "Nova is an assistant.")
    assert add_file(path, index, FakeEmbedder()) == {"source": "notes.md", "chunks": 1}
    assert index.list_documents() == [
        {"source": "notes.md", "chunks": 1, "model": "fake/3"}
    ]


def test_a_long_file_becomes_several_chunks(tmp_path, index):
    path = write(tmp_path, "long.txt", "word " * 1000)
    result = add_file(path, index, FakeEmbedder())
    assert result["chunks"] > 1
    assert index.list_documents()[0]["chunks"] == result["chunks"]


def test_adding_the_same_file_again_replaces_it(tmp_path, index):
    path = write(tmp_path, "notes.md", "first version")
    add_file(path, index, FakeEmbedder())
    path.write_text("second version", encoding="utf-8")
    add_file(path, index, FakeEmbedder())
    assert len(index.list_documents()) == 1


def test_other_file_types_are_refused(tmp_path, index):
    path = write(tmp_path, "paper.pdf", "text")
    with pytest.raises(IngestError):
        add_file(path, index, FakeEmbedder())


def test_a_missing_file_is_refused(tmp_path, index):
    with pytest.raises(IngestError):
        add_file(tmp_path / "nope.md", index, FakeEmbedder())


def test_a_folder_is_refused(tmp_path, index):
    (tmp_path / "dir.md").mkdir()
    with pytest.raises(IngestError):
        add_file(tmp_path / "dir.md", index, FakeEmbedder())


def test_an_empty_file_is_refused(tmp_path, index):
    path = write(tmp_path, "empty.md", "  \n ")
    with pytest.raises(IngestError):
        add_file(path, index, FakeEmbedder())


def test_a_huge_file_is_refused(tmp_path, index):
    path = write(tmp_path, "big.txt", "a" * (MAX_FILE_BYTES + 1))
    with pytest.raises(IngestError):
        add_file(path, index, FakeEmbedder())


def test_a_file_that_is_not_text_is_refused(tmp_path, index):
    path = tmp_path / "binary.txt"
    path.write_bytes(b"\xff\xff\xff")
    with pytest.raises(IngestError):
        add_file(path, index, FakeEmbedder())


def test_too_many_chunks_is_refused(tmp_path, index, monkeypatch):
    monkeypatch.setattr("rag.ingest.chunk_text", lambda text: ["x"] * 501)
    path = write(tmp_path, "notes.md", "text")
    with pytest.raises(IngestError):
        add_file(path, index, FakeEmbedder())


def test_nothing_is_stored_when_embedding_fails(tmp_path, index):
    path = write(tmp_path, "notes.md", "text")
    with pytest.raises(EmbedError):
        add_file(path, index, FailingEmbedder())
    assert index.list_documents() == []