from workflows import store_factory
from workflows.store import WorkflowStore


def test_files_by_default(monkeypatch):
    monkeypatch.setattr(store_factory, "load_dotenv", lambda: None)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    assert isinstance(store_factory.create_workflow_store(), WorkflowStore)


def test_postgres_when_url_is_set(monkeypatch):
    monkeypatch.setattr(store_factory, "load_dotenv", lambda: None)
    monkeypatch.setenv("DATABASE_URL", "postgresql://fake")
    created = []

    class Fake:
        def __init__(self, url):
            created.append(url)

    monkeypatch.setattr("workflows.postgres_store.PostgresWorkflowStore", Fake)
    store = store_factory.create_workflow_store()
    assert isinstance(store, Fake)
    assert created == ["postgresql://fake"]