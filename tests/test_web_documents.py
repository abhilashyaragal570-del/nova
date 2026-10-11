import base64
import io

import pytest

from rag.embedder import EmbedError
from rag.file_index import FileDocumentIndex
from rag.index import RagIndexError
from rag.ingest import MAX_FILE_BYTES
from web import server


class FakeEmbedder:
    signature = "fake/3"

    def embed_documents(self, texts):
        return [[1.0, 0.0, 0.0] for _ in texts]


class FailingEmbedder:
    signature = "fake/3"

    def embed_documents(self, texts):
        raise EmbedError("no network")


class BrokenIndex:
    def add_document(self, *args, **kwargs):
        raise RagIndexError("the index was built with a different embedding model")

    def list_documents(self):
        raise RagIndexError("the index is unavailable")

    def remove_document(self, source):
        raise RagIndexError("the index is unavailable")


def basic(pw):
    token = base64.b64encode(f"nova:{pw}".encode()).decode()
    return {"Authorization": "Basic " + token}


@pytest.fixture
def index(tmp_path):
    return FileDocumentIndex(tmp_path / "idx")


@pytest.fixture
def anon_client(monkeypatch, index):
    # Never touch the real index or call Gemini
    monkeypatch.setattr(server, "get_document_index", lambda: index)
    monkeypatch.setattr(server, "get_embedder", lambda: FakeEmbedder())
    monkeypatch.setenv("NOVA_PASSWORD", "secret")
    server.app.config["TESTING"] = True
    return server.app.test_client()


@pytest.fixture
def client(anon_client):
    # Same client, but it sends the right password with every request
    anon_client.environ_base["HTTP_AUTHORIZATION"] = basic("secret")["Authorization"]
    return anon_client


def upload(client, name, data):
    return client.post(
        "/documents",
        data={"file": (io.BytesIO(data), name)},
        content_type="multipart/form-data",
    )


def test_documents_need_the_password(anon_client):
    assert anon_client.get("/documents").status_code == 401
    assert anon_client.post("/documents").status_code == 401
    assert anon_client.delete("/documents/notes.md").status_code == 401
    wrong = basic("wrong")
    assert anon_client.get("/documents", headers=wrong).status_code == 401


def test_the_list_starts_empty(client):
    res = client.get("/documents")
    assert res.status_code == 200
    assert res.get_json() == []


def test_an_uploaded_file_is_listed(client):
    res = upload(client, "notes.md", b"Nova is an assistant.")
    assert res.status_code == 201
    assert res.get_json() == {"source": "notes.md", "chunks": 1}
    assert client.get("/documents").get_json() == [
        {"source": "notes.md", "chunks": 1, "model": "fake/3"}
    ]


def test_uploading_the_same_name_again_replaces_it(client):
    upload(client, "notes.md", b"first version")
    upload(client, "notes.md", b"second version")
    assert len(client.get("/documents").get_json()) == 1


def test_an_upload_name_loses_its_folders(client):
    res = upload(client, "../../evil/x.md", b"text")
    assert res.status_code == 201
    assert res.get_json()["source"] == "x.md"


def test_a_request_without_a_file_is_refused(client):
    res = client.post("/documents")
    assert res.status_code == 400
    assert "Choose a file" in res.get_json()["error"]


def test_another_file_type_is_refused(client):
    res = upload(client, "paper.pdf", b"text")
    assert res.status_code == 400
    assert ".txt and .md" in res.get_json()["error"]
    assert client.get("/documents").get_json() == []


def test_an_empty_file_is_refused(client):
    res = upload(client, "empty.md", b"  \n ")
    assert res.status_code == 400
    assert "empty" in res.get_json()["error"]


def test_a_file_that_is_not_text_is_refused(client):
    res = upload(client, "binary.txt", b"\xff\xff\xff")
    assert res.status_code == 400


def test_a_file_just_over_the_limit_is_refused(client):
    res = upload(client, "big.txt", b"a" * (MAX_FILE_BYTES + 1))
    assert res.status_code == 400
    assert "too large" in res.get_json()["error"]


def test_a_huge_request_is_refused_with_a_json_error(client):
    res = upload(client, "huge.txt", b"a" * (MAX_FILE_BYTES + 300_000))
    assert res.status_code == 413
    assert "too large" in res.get_json()["error"]


def test_an_embedding_failure_is_reported_and_nothing_is_stored(
    client, monkeypatch, index
):
    monkeypatch.setattr(server, "get_embedder", lambda: FailingEmbedder())
    res = upload(client, "notes.md", b"text")
    assert res.status_code == 502
    assert "no network" in res.get_json()["error"]
    assert index.list_documents() == []


def test_an_index_problem_on_upload_is_reported(client, monkeypatch):
    monkeypatch.setattr(server, "get_document_index", lambda: BrokenIndex())
    res = upload(client, "notes.md", b"text")
    assert res.status_code == 409
    assert "different embedding model" in res.get_json()["error"]


def test_an_index_problem_on_list_is_reported(client, monkeypatch):
    monkeypatch.setattr(server, "get_document_index", lambda: BrokenIndex())
    assert client.get("/documents").status_code == 503


def test_a_document_can_be_removed(client):
    upload(client, "notes.md", b"text")
    assert client.delete("/documents/notes.md").status_code == 200
    assert client.get("/documents").get_json() == []


def test_a_name_with_spaces_can_be_removed(client):
    upload(client, "my notes.md", b"text")
    assert client.delete("/documents/my%20notes.md").status_code == 200
    assert client.get("/documents").get_json() == []


def test_removing_a_missing_document_is_a_404(client):
    assert client.delete("/documents/nope.md").status_code == 404


def test_an_index_problem_on_remove_is_reported(client, monkeypatch):
    monkeypatch.setattr(server, "get_document_index", lambda: BrokenIndex())
    assert client.delete("/documents/notes.md").status_code == 503