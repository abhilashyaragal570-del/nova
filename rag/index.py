"""Shared pieces of the document index: errors, checks and ranking.

Both stores (files, PostgreSQL) use these, so they accept and rank the same
way. A store holds chunks of text with their vectors. Vectors only compare
when they came from the same embedding model, so every document records the
model signature and the index refuses to mix them.
"""
import math
from typing import Any, Iterable, Sequence

MAX_SOURCE_CHARS = 200
MAX_CHUNKS_PER_DOCUMENT = 500
MAX_TOP_K = 20
MODEL_MISMATCH = (
    "the index was built with a different embedding model; "
    "remove the old documents (python -m rag clear) and add them again"
)


class RagIndexError(Exception):
    """Raised when the document index cannot do what was asked."""


def dot(a: Sequence[float], b: Sequence[float]) -> float:
    return sum(x * y for x, y in zip(a, b))


def check_document(source: Any, chunks: Any, vectors: Any, model: Any) -> None:
    if not isinstance(source, str) or not source.strip() or len(source) > MAX_SOURCE_CHARS:
        raise RagIndexError(f"source must be 1 to {MAX_SOURCE_CHARS} characters")
    if not isinstance(model, str) or not model.strip():
        raise RagIndexError("model name is missing")
    if not isinstance(chunks, list) or not isinstance(vectors, list) or not chunks:
        raise RagIndexError("a document needs at least one chunk")
    if len(chunks) != len(vectors):
        raise RagIndexError("chunks and vectors must be the same length")
    if len(chunks) > MAX_CHUNKS_PER_DOCUMENT:
        raise RagIndexError(f"too many chunks (max {MAX_CHUNKS_PER_DOCUMENT})")
    if not all(isinstance(c, str) and c.strip() for c in chunks):
        raise RagIndexError("chunks must be non-empty text")
    width = len(vectors[0]) if isinstance(vectors[0], list) else 0
    if width == 0 or not all(isinstance(v, list) and len(v) == width for v in vectors):
        raise RagIndexError("vectors must all be non-empty lists of the same size")
    if not all(
        isinstance(x, (int, float)) and math.isfinite(x) for v in vectors for x in v
    ):
        raise RagIndexError("vectors must contain only finite numbers")


def rank(
    rows: Iterable[tuple[str, int, str, str, Sequence[float]]],
    query_vector: Sequence[float],
    model: str,
    top_k: Any,
) -> list[dict[str, Any]]:
    """rows are (source, chunk_index, text, model, vector). Best match first."""
    try:
        top_k = int(top_k)
    except (TypeError, ValueError):
        raise RagIndexError("top_k must be a number") from None
    top_k = max(1, min(top_k, MAX_TOP_K))
    results = []
    for source, chunk_index, text, row_model, vector in rows:
        if row_model != model or len(vector) != len(query_vector):
            raise RagIndexError(MODEL_MISMATCH)
        results.append(
            {
                "source": source,
                "chunk": chunk_index,
                "text": text,
                "score": dot(vector, query_vector),
            }
        )
    results.sort(key=lambda r: r["score"], reverse=True)
    return results[:top_k]