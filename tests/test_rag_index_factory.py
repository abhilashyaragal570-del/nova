from rag import index_factory
from rag.file_index import FileDocumentIndex


def test_files_by_default(monkeypatch):
    monkeypatch.setattr(index_factory, "load_dotenv", lambda: None)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    assert isinstance(index_factory.create_document_index(), FileDocumentIndex)


def test_postgres_when_url_is_set(monkeypatch):
    monkeypatch.setattr(index_factory, "load_dotenv", lambda: None)
    monkeypatch.setenv("DATABASE_URL", "postgresql://fake")
    created = []

    class Fake:
        def __init__(self, url):
            created.append(url)

    monkeypatch.setattr("rag.postgres_index.PostgresDocumentIndex", Fake)
    index = index_factory.create_document_index()
    assert isinstance(index, Fake)
    assert created == ["postgresql://fake"]