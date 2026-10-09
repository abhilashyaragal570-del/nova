from types import SimpleNamespace

import pytest

from rag import embedder as embedder_module
from rag.embedder import (
    DEFAULT_MODEL,
    MAX_ATTEMPTS,
    EmbedError,
    GeminiEmbedder,
    normalize,
)


class FakeError(Exception):
    def __init__(self, code):
        super().__init__(f"error {code}")
        self.code = code


class FakeModels:
    def __init__(self, failures=()):
        self.calls = []
        self.failures = list(failures)

    def embed_content(self, model, contents, config):
        self.calls.append({"model": model, "contents": list(contents), "config": config})
        if self.failures:
            raise self.failures.pop(0)
        return SimpleNamespace(
            embeddings=[SimpleNamespace(values=[float(len(t)), 1.0, 0.0]) for t in contents]
        )


class FakeClient:
    def __init__(self, failures=()):
        self.models = FakeModels(failures)


def make(client=None, **kwargs):
    client = client or FakeClient()
    kwargs.setdefault("sleep", lambda seconds: None)
    kwargs.setdefault("model", "test-model")
    return GeminiEmbedder(client=client, **kwargs), client


def test_documents_come_back_normalized_one_per_text():
    emb, _ = make()
    vectors = emb.embed_documents(["a", "bb"])
    assert len(vectors) == 2
    for v in vectors:
        assert sum(x * x for x in v) == pytest.approx(1.0)


def test_documents_use_the_document_task_and_settings():
    emb, client = make()
    emb.embed_documents(["a"])
    call = client.models.calls[0]
    assert call["model"] == "test-model"
    assert call["config"].task_type == "RETRIEVAL_DOCUMENT"
    assert call["config"].output_dimensionality == 768


def test_query_uses_the_query_task_and_returns_one_vector():
    emb, client = make()
    vector = emb.embed_query("what is nova")
    assert client.models.calls[0]["config"].task_type == "RETRIEVAL_QUERY"
    assert isinstance(vector, list) and isinstance(vector[0], float)


def test_texts_are_sent_in_batches():
    emb, client = make(batch_size=50)
    vectors = emb.embed_documents([f"t{i}" for i in range(120)])
    assert len(vectors) == 120
    assert [len(c["contents"]) for c in client.models.calls] == [50, 50, 20]


def test_no_texts_means_no_call():
    emb, client = make()
    assert emb.embed_documents([]) == []
    assert client.models.calls == []


def test_blank_text_is_refused_before_any_call():
    emb, client = make()
    with pytest.raises(EmbedError):
        emb.embed_documents(["ok", "   "])
    with pytest.raises(EmbedError):
        emb.embed_query("")
    assert client.models.calls == []


def test_model_defaults_and_can_be_set_by_environment(monkeypatch):
    monkeypatch.setattr(embedder_module, "load_dotenv", lambda: None)
    monkeypatch.delenv("NOVA_EMBED_MODEL", raising=False)
    assert GeminiEmbedder(client=FakeClient()).model == DEFAULT_MODEL
    monkeypatch.setenv("NOVA_EMBED_MODEL", "other-model")
    assert GeminiEmbedder(client=FakeClient()).model == "other-model"


def test_temporary_errors_are_retried_with_backoff():
    sleeps = []
    emb, client = make(
        client=FakeClient([FakeError(503), FakeError(429)]), sleep=sleeps.append
    )
    assert len(emb.embed_documents(["a"])) == 1
    assert len(client.models.calls) == 3
    assert sleeps == [2.0, 4.0]


def test_it_gives_up_after_the_last_attempt():
    emb, client = make(client=FakeClient([FakeError(503)] * MAX_ATTEMPTS))
    with pytest.raises(EmbedError):
        emb.embed_documents(["a"])
    assert len(client.models.calls) == MAX_ATTEMPTS


def test_other_errors_are_not_retried():
    emb, client = make(client=FakeClient([ValueError("bad")]))
    with pytest.raises(EmbedError):
        emb.embed_documents(["a"])
    assert len(client.models.calls) == 1


def test_wrong_number_of_vectors_is_an_error():
    class ShortModels:
        def embed_content(self, model, contents, config):
            return SimpleNamespace(embeddings=[])

    emb, _ = make(client=SimpleNamespace(models=ShortModels()))
    with pytest.raises(EmbedError):
        emb.embed_documents(["a"])


def test_normalize():
    assert normalize([3, 4]) == pytest.approx([0.6, 0.8])
    with pytest.raises(EmbedError):
        normalize([0, 0])
    with pytest.raises(EmbedError):
        normalize([])
    with pytest.raises(EmbedError):
        normalize(["x"])