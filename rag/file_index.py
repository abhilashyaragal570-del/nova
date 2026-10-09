"""Document index kept in local files: one JSON file per document.

Each file holds a document's chunks and vectors. Files are named by a hash
of the source name, so a source name can never point outside the folder.
Writes are atomic: temp file, then rename.
"""
import hashlib
import json
import logging
import os
import tempfile
from pathlib import Path
from typing import Any, Sequence

from rag.index import MODEL_MISMATCH, RagIndexError, check_document, rank

logger = logging.getLogger(__name__)

DEFAULT_DIR = Path("rag_data")


def _doc_id(source: str) -> str:
    return hashlib.sha256(source.encode("utf-8")).hexdigest()[:24]


class FileDocumentIndex:
    def __init__(self, directory: Path | str = DEFAULT_DIR) -> None:
        self.directory = Path(directory)
        self._docs = self.directory / "docs"

    def _path(self, source: str) -> Path:
        return self._docs / f"{_doc_id(source)}.json"

    def _read_all(self) -> list[dict[str, Any]]:
        if not self._docs.is_dir():
            return []
        docs = []
        for path in sorted(self._docs.glob("*.json")):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                good = (
                    isinstance(data.get("source"), str)
                    and isinstance(data.get("model"), str)
                    and isinstance(data.get("chunks"), list)
                    and all(
                        isinstance(c, dict)
                        and isinstance(c.get("text"), str)
                        and isinstance(c.get("vector"), list)
                        for c in data["chunks"]
                    )
                )
                if not good:
                    raise ValueError("unexpected shape")
            except (OSError, ValueError, AttributeError):
                logger.warning("skipping unreadable index file %s", path.name)
                continue
            docs.append(data)
        return docs

    def add_document(
        self, source: str, chunks: list[str], vectors: list[list[float]], model: str
    ) -> None:
        check_document(source, chunks, vectors, model)
        if any(d["model"] != model for d in self._read_all() if d["source"] != source):
            raise RagIndexError(MODEL_MISMATCH)
        data = {
            "source": source,
            "model": model,
            "chunks": [{"text": t, "vector": v} for t, v in zip(chunks, vectors)],
        }
        try:
            text = json.dumps(data, ensure_ascii=False, allow_nan=False)
        except (TypeError, ValueError) as e:
            raise RagIndexError(f"document cannot be stored: {e}") from None
        path = self._path(source)
        try:
            self._docs.mkdir(parents=True, exist_ok=True)
            fd, tmp = tempfile.mkstemp(dir=self._docs, suffix=".tmp")
            try:
                with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
                    f.write(text)
                os.replace(tmp, path)
            except BaseException:
                Path(tmp).unlink(missing_ok=True)
                raise
        except OSError as e:
            raise RagIndexError(f"could not save the document: {type(e).__name__}") from None

    def remove_document(self, source: str) -> bool:
        if not isinstance(source, str) or not source:
            return False
        try:
            self._path(source).unlink()
        except FileNotFoundError:
            return False
        except OSError as e:
            raise RagIndexError(f"could not remove the document: {type(e).__name__}") from None
        return True

    def list_documents(self) -> list[dict[str, Any]]:
        return sorted(
            (
                {"source": d["source"], "chunks": len(d["chunks"]), "model": d["model"]}
                for d in self._read_all()
            ),
            key=lambda item: item["source"],
        )

    def clear(self) -> int:
        """Remove every document. Returns how many were removed."""
        if not self._docs.is_dir():
            return 0
        removed = 0
        for path in self._docs.glob("*.json"):
            try:
                path.unlink()
                removed += 1
            except OSError as e:
                raise RagIndexError(f"could not clear the index: {type(e).__name__}") from None
        return removed

    def search(
        self, query_vector: Sequence[float], model: str, top_k: int = 5
    ) -> list[dict[str, Any]]:
        rows = [
            (d["source"], i, c["text"], d["model"], c["vector"])
            for d in self._read_all()
            for i, c in enumerate(d["chunks"])
        ]
        return rank(rows, query_vector, model, top_k)