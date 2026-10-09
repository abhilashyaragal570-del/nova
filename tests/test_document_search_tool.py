import pytest

from rag.embedder import EmbedError
from rag.file_index import FileDocumentIndex
from tools import document_search
from tools.document_search import (
    DEFAULT_RESULTS,
    MAX_QUERY_LENGTH,
    MAX_RESULTS_LIMIT,
    MAX_TEXT_LENGTH,
    DocumentSearchTool,
)
from tools.registry import ToolRegistry

X, Y = [1.0, 0.0, 0.0], [0.0, 1.0, 0.0]


class FakeEmbedder:
    signature = "fake/3"

    def __init__(self):
        self.queries = []

    def embed_query(self, text):
        self.queries.append(text)
        return X if "cat" in text.lower() else Y


class OtherModelEmbedder(FakeEmbedder):
    signature = "other/3"


class FailingEmbedder:
    signature = "fake/3"

    def embed_query(self, text):
        raise EmbedError("no network")


@pytest.fixture
def index(tmp_path):
    idx = FileDocumentIndex(tmp_path / "idx")
    idx.add_document("cat.md", ["cats purr"], [X], "fake/3")
    idx.add_document("dog.md", ["dogs bark"], [Y], "fake/3")
    return idx


def make(index, embedder=None):
    return DocumentSearchTool(index=index, embedder=embedder or FakeEmbedder())


def test_tool_description():
    tool = DocumentSearchTool()
    assert tool.name == "search_documents"
    assert tool.read_only is True
    assert tool.parameters["required"] == ["query"]


def test_best_match_comes_first(index):
    result = make(index).run(query="tell me about cats")
    assert result.ok
    assert result.output[0]["source"] == "cat.md"
    assert result.output[0]["text"] == "cats purr"
    assert set(result.output[0]) == {"source", "chunk", "text", "score"}


def test_max_results_limits_the_answer(index):
    assert len(make(index).run(query="cats", max_results=1).output) == 1


def test_max_results_is_clamped(index):
    index.add_document("many.md", ["t"] * 8, [X] * 8, "fake/3")
    result = make(index).run(query="cats", max_results=100)
    assert len(result.output) == MAX_RESULTS_LIMIT


def test_a_bad_max_results_uses_the_default(index):
    index.add_document("many.md", ["t"] * 8, [X] * 8, "fake/3")
    result = make(index).run(query="cats", max_results="lots")
    assert len(result.output) == DEFAULT_RESULTS


@pytest.mark.parametrize("query", [None, "", "   ", 5])
def test_a_blank_query_is_refused_before_any_call(index, query):
    embedder = FakeEmbedder()
    result = make(index, embedder).run(query=query)
    assert not result.ok
    assert embedder.queries == []


def test_a_long_query_is_refused(index):
    result = make(index).run(query="a" * (MAX_QUERY_LENGTH + 1))
    assert not result.ok


def test_an_empty_index_fails_without_calling_gemini(tmp_path):
    embedder = FakeEmbedder()
    tool = DocumentSearchTool(index=FileDocumentIndex(tmp_path / "empty"), embedder=embedder)
    result = tool.run(query="cats")
    assert not result.ok
    assert "No documents" in result.error
    assert embedder.queries == []


def test_an_embedding_failure_is_returned_not_raised(index):
    result = make(index, FailingEmbedder()).run(query="cats")
    assert not result.ok
    assert "no network" in result.error


def test_a_different_embedding_model_is_reported(index):
    result = make(index, OtherModelEmbedder()).run(query="cats")
    assert not result.ok
    assert "different embedding model" in result.error


def test_long_passages_are_cut(tmp_path):
    idx = FileDocumentIndex(tmp_path / "idx")
    idx.add_document("long.md", ["x" * 2000], [X], "fake/3")
    result = make(idx).run(query="cats")
    assert len(result.output[0]["text"]) == MAX_TEXT_LENGTH


def test_creating_the_tool_touches_nothing(monkeypatch):
    def boom(*args, **kwargs):
        raise AssertionError("should not be created yet")

    monkeypatch.setattr(document_search, "create_document_index", boom)
    monkeypatch.setattr(document_search, "GeminiEmbedder", boom)
    DocumentSearchTool()


def test_it_works_through_the_registry(index):
    registry = ToolRegistry()
    registry.register(make(index))
    result = registry.execute("search_documents", {"query": "cats"})
    assert result.ok
    assert result.output[0]["source"] == "cat.md"