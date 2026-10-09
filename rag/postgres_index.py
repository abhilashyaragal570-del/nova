"""PostgreSQL version of the document index.

Same methods as rag.file_index.FileDocumentIndex. One row per chunk, with the
vector in a DOUBLE PRECISION[] column. Search reads the chunks and ranks them
in Python, which is plenty fast for a personal document set.
"""
import re
from typing import Any, Sequence

import psycopg

from rag.index import MODEL_MISMATCH, RagIndexError, check_document, rank

DEFAULT_TABLE = "rag_chunks"
_TABLE_RE = re.compile(r"^[a-z_][a-z0-9_]{0,40}$")


class PostgresDocumentIndex:
    def __init__(self, database_url: str, table: str = DEFAULT_TABLE) -> None:
        if not isinstance(table, str) or not _TABLE_RE.match(table):
            raise RagIndexError("invalid table name")
        self.database_url = database_url
        self.table = table
        try:
            with psycopg.connect(self.database_url) as conn:
                conn.execute(
                    f"""
                    CREATE TABLE IF NOT EXISTS {self.table} (
                        source       TEXT NOT NULL,
                        chunk_index  INTEGER NOT NULL,
                        text         TEXT NOT NULL,
                        model        TEXT NOT NULL,
                        embedding    DOUBLE PRECISION[] NOT NULL,
                        PRIMARY KEY (source, chunk_index)
                    )
                    """
                )
        except psycopg.Error as e:
            raise RagIndexError(
                f"could not set up the document table: {type(e).__name__}"
            ) from None

    def add_document(
        self, source: str, chunks: list[str], vectors: list[list[float]], model: str
    ) -> None:
        check_document(source, chunks, vectors, model)
        rows = [(source, i, t, model, v) for i, (t, v) in enumerate(zip(chunks, vectors))]
        try:
            with psycopg.connect(self.database_url) as conn:
                others = conn.execute(
                    f"SELECT DISTINCT model FROM {self.table} WHERE source <> %s", (source,)
                ).fetchall()
                if any(r[0] != model for r in others):
                    raise RagIndexError(MODEL_MISMATCH)
                conn.execute(f"DELETE FROM {self.table} WHERE source = %s", (source,))
                with conn.cursor() as cur:
                    cur.executemany(
                        f"INSERT INTO {self.table} "
                        "(source, chunk_index, text, model, embedding) "
                        "VALUES (%s, %s, %s, %s, %s)",
                        rows,
                    )
        except psycopg.Error as e:
            raise RagIndexError(f"could not save the document: {type(e).__name__}") from None

    def remove_document(self, source: str) -> bool:
        if not isinstance(source, str) or not source:
            return False
        try:
            with psycopg.connect(self.database_url) as conn:
                cur = conn.execute(f"DELETE FROM {self.table} WHERE source = %s", (source,))
                return cur.rowcount > 0
        except psycopg.Error as e:
            raise RagIndexError(f"could not remove the document: {type(e).__name__}") from None

    def list_documents(self) -> list[dict[str, Any]]:
        try:
            with psycopg.connect(self.database_url) as conn:
                rows = conn.execute(
                    f"SELECT source, count(*), min(model) FROM {self.table} "
                    "GROUP BY source ORDER BY source"
                ).fetchall()
        except psycopg.Error as e:
            raise RagIndexError(f"could not list documents: {type(e).__name__}") from None
        return [{"source": s, "chunks": int(n), "model": m} for s, n, m in rows]

    def clear(self) -> int:
        """Remove every document. Returns how many were removed."""
        try:
            with psycopg.connect(self.database_url) as conn:
                count = conn.execute(
                    f"SELECT count(DISTINCT source) FROM {self.table}"
                ).fetchone()[0]
                conn.execute(f"DELETE FROM {self.table}")
        except psycopg.Error as e:
            raise RagIndexError(f"could not clear the index: {type(e).__name__}") from None
        return int(count)

    def search(
        self, query_vector: Sequence[float], model: str, top_k: int = 5
    ) -> list[dict[str, Any]]:
        try:
            with psycopg.connect(self.database_url) as conn:
                rows = conn.execute(
                    f"SELECT source, chunk_index, text, model, embedding FROM {self.table}"
                ).fetchall()
        except psycopg.Error as e:
            raise RagIndexError(f"could not search: {type(e).__name__}") from None
        return rank(rows, query_vector, model, top_k)