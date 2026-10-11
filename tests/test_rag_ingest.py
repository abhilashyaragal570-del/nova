import pytest

from rag.embedder import EmbedError
from rag.file_index import FileDocumentIndex
from rag.ingest import (
    MAX_FILE_BYTES,
    IngestError,
    add_file,
    add_text,
    add_upload,
)


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


# --- text and upload entry points (used by the web upload) ---


def test_add_text_stores_a_document(index):
    result = add_text("notes.md", "Nova is an assistant.", index, FakeEmbedder())
    assert result == {"source": "notes.md", "chunks": 1}
    assert index.list_documents() == [
        {"source": "notes.md", "chunks": 1, "model": "fake/3"}
    ]


def test_an_upload_is_stored_from_bytes(index):
    result = add_upload("notes.md", b"Nova is an assistant.", index, FakeEmbedder())
    assert result == {"source": "notes.md", "chunks": 1}
    assert index.list_documents()[0]["source"] == "notes.md"


def test_an_upload_with_a_bom_is_read(index):
    data = "\ufeffhello".encode("utf-8")
    add_upload("notes.txt", data, index, FakeEmbedder())
    assert index.list_documents()[0]["source"] == "notes.txt"


def test_uploading_the_same_name_again_replaces_it(index):
    add_upload("notes.md", b"first version", index, FakeEmbedder())
    add_upload("notes.md", b"second version", index, FakeEmbedder())
    assert len(index.list_documents()) == 1


@pytest.mark.parametrize(
    "filename",
    ["../../evil/notes.md", "C:\\Users\\me\\notes.md", "folder/notes.md", "/etc/notes.md"],
)
def test_an_upload_name_loses_its_folders(index, filename):
    add_upload(filename, b"text", index, FakeEmbedder())
    assert index.list_documents()[0]["source"] == "notes.md"


@pytest.mark.parametrize("filename", ["", "..", ".", "folder/", None, 5, "bad\x00name.md"])
def test_an_invalid_upload_name_is_refused(index, filename):
    with pytest.raises(IngestError):
        add_upload(filename, b"text", index, FakeEmbedder())
    assert index.list_documents() == []


def test_an_upload_name_that_is_too_long_is_refused(index):
    with pytest.raises(IngestError):
        add_upload("a" * 201 + ".md", b"text", index, FakeEmbedder())


def test_an_upload_of_another_type_is_refused(index):
    with pytest.raises(IngestError):
        add_upload("paper.pdf", b"text", index, FakeEmbedder())


def test_an_empty_upload_is_refused(index):
    with pytest.raises(IngestError):
        add_upload("empty.md", b"  \n ", index, FakeEmbedder())


def test_a_huge_upload_is_refused(index):
    with pytest.raises(IngestError):
        add_upload("big.txt", b"a" * (MAX_FILE_BYTES + 1), index, FakeEmbedder())


def test_an_upload_that_is_not_text_is_refused(index):
    with pytest.raises(IngestError):
        add_upload("binary.txt", b"\xff\xff\xff", index, FakeEmbedder())


def test_nothing_is_stored_when_an_upload_fails_to_embed(index):
    with pytest.raises(EmbedError):
        add_upload("notes.md", b"text", index, FailingEmbedder())
    assert index.list_documents() == []