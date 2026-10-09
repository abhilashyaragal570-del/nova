"""Turn text into vectors with the Gemini embedding API.

Vectors are scaled to length 1, so searching later is a plain dot product.
The client is passed in (or taken lazily from app.llm), so tests use a fake
and never call Gemini. Every failure becomes EmbedError.
"""
import math
import os
import time
from typing import Any, Callable, Iterable

from dotenv import load_dotenv
from google.genai import types

DEFAULT_MODEL = "gemini-embedding-001"
DEFAULT_DIMENSIONS = 768
DEFAULT_BATCH_SIZE = 50
RETRY_CODES = {429, 500, 502, 503, 504}
MAX_ATTEMPTS = 4
BACKOFF_SECONDS = 2.0


class EmbedError(Exception):
    """Raised when text cannot be embedded."""


def normalize(vector: Iterable[Any]) -> list[float]:
    try:
        values = [float(x) for x in vector]
    except (TypeError, ValueError):
        raise EmbedError("embedding contains a non-number") from None
    length = math.sqrt(sum(x * x for x in values))
    if not values or length == 0 or not math.isfinite(length):
        raise EmbedError("embedding is empty or all zeros")
    return [x / length for x in values]


class GeminiEmbedder:
    def __init__(
        self,
        client: Any = None,
        model: str | None = None,
        dimensions: int = DEFAULT_DIMENSIONS,
        batch_size: int = DEFAULT_BATCH_SIZE,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        if model is None:
            load_dotenv()
            model = os.environ.get("NOVA_EMBED_MODEL") or DEFAULT_MODEL
        self.model = model
        self.dimensions = dimensions
        self.batch_size = max(1, batch_size)
        self._client = client
        self._sleep = sleep
        
    @property
    def signature(self) -> str:
        """Names the model and vector size. Vectors only compare within one signature."""
        return f"{self.model}/{self.dimensions}"    

    def _get_client(self) -> Any:
        if self._client is None:
            try:
                from app.llm import client  # lazy: importing it creates the Gemini client

                self._client = client
            except Exception:
                raise EmbedError("could not start the Gemini client") from None
        return self._client

    def _call(self, batch: list[str], task_type: str) -> list[list[float]]:
        client = self._get_client()
        config = types.EmbedContentConfig(
            task_type=task_type, output_dimensionality=self.dimensions
        )
        for attempt in range(1, MAX_ATTEMPTS + 1):
            try:
                result = client.models.embed_content(
                    model=self.model, contents=batch, config=config
                )
                break
            except Exception as e:
                if getattr(e, "code", None) in RETRY_CODES and attempt < MAX_ATTEMPTS:
                    self._sleep(BACKOFF_SECONDS * 2 ** (attempt - 1))
                    continue
                raise EmbedError(f"embedding call failed: {type(e).__name__}") from None
        items = getattr(result, "embeddings", None)
        if not isinstance(items, list) or len(items) != len(batch):
            raise EmbedError("embedding service returned an unexpected answer")
        return [normalize(getattr(item, "values", None) or []) for item in items]

    def embed_documents(self, texts: Iterable[str]) -> list[list[float]]:
        texts = list(texts)
        for t in texts:
            if not isinstance(t, str) or not t.strip():
                raise EmbedError("cannot embed empty text")
        vectors: list[list[float]] = []
        for i in range(0, len(texts), self.batch_size):
            vectors.extend(self._call(texts[i : i + self.batch_size], "RETRIEVAL_DOCUMENT"))
        return vectors

    def embed_query(self, text: str) -> list[float]:
        if not isinstance(text, str) or not text.strip():
            raise EmbedError("cannot embed empty text")
        return self._call([text], "RETRIEVAL_QUERY")[0]