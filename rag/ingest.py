"""Read a text file, split it, embed it and store it in the document index.

The index and the embedder are passed in, so tests use fakes. Problems with
the file become IngestError. Embedding and storage problems keep their own
errors (EmbedError, RagIndexError) so the caller can tell them apart.

Files come in two ways: add_file reads a path (the terminal command) and
add_upload takes a name and bytes (the web upload). Both end in add_text,
so they apply the same limits.
"""
import posixpath
from pathlib import Path

from rag.chunker import chunk_text
from rag.index import MAX_CHUNKS_PER_DOCUMENT, MAX_SOURCE_CHARS

ALLOWED_SUFFIXES = {".txt", ".md"}
MAX_FILE_BYTES = 300_000


class IngestError(Exception):
    """Raised when a file cannot be added to the index."""


def check_suffix(name) -> None:
    if Path(name).suffix.lower() not in ALLOWED_SUFFIXES:
        raise IngestError("only .txt and .md files can be added")


def read_document(path) -> str:
    path = Path(path)
    check_suffix(path.name)
    try:
        if not path.is_file():
            raise IngestError(f"not a file: {path}")
        if path.stat().st_size > MAX_FILE_BYTES:
            raise IngestError(f"file is too large (max {MAX_FILE_BYTES // 1000} KB)")
        text = path.read_text(encoding="utf-8-sig")
    except UnicodeDecodeError:
        raise IngestError("the file is not valid UTF-8 text") from None
    except OSError as e:
        raise IngestError(f"could not read the file: {type(e).__name__}") from None
    if not text.strip():
        raise IngestError("the file is empty")
    return text


def clean_name(filename) -> str:
    """Reduce a browser-supplied file name to a plain name with no folders."""
    if not isinstance(filename, str):
        raise IngestError("the file has no name")
    name = posixpath.basename(filename.replace("\\", "/")).strip()
    if not name or name in {".", ".."} or any(ord(c) < 32 for c in name):
        raise IngestError("the file name is not valid")
    return name


def decode_upload(data: bytes) -> str:
    if len(data) > MAX_FILE_BYTES:
        raise IngestError(f"file is too large (max {MAX_FILE_BYTES // 1000} KB)")
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise IngestError("the file is not valid UTF-8 text") from None
    if not text.strip():
        raise IngestError("the file is empty")
    return text


def add_text(source, text, index, embedder) -> dict:
    """Chunk, embed and store text under a source name, replacing any old copy."""
    if len(source) > MAX_SOURCE_CHARS:
        raise IngestError("the file name is too long")
    chunks = chunk_text(text)
    if len(chunks) > MAX_CHUNKS_PER_DOCUMENT:
        raise IngestError("the file is too long; split it into smaller files")
    vectors = embedder.embed_documents(chunks)
    index.add_document(source, chunks, vectors, embedder.signature)
    return {"source": source, "chunks": len(chunks)}


def add_file(path, index, embedder) -> dict:
    """Add one file to the index, replacing it if it is already there."""
    path = Path(path)
    text = read_document(path)
    return add_text(path.name, text, index, embedder)


def add_upload(filename, data: bytes, index, embedder) -> dict:
    """Add an uploaded file (name and bytes), replacing it if already there."""
    name = clean_name(filename)
    check_suffix(name)
    text = decode_upload(data)
    return add_text(name, text, index, embedder)