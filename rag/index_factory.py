"""Pick the document index: PostgreSQL if DATABASE_URL is set, else files."""
import os

from dotenv import load_dotenv

from rag.file_index import FileDocumentIndex


def create_document_index():
    load_dotenv()
    url = os.environ.get("DATABASE_URL")
    if url:
        from rag.postgres_index import PostgresDocumentIndex

        return PostgresDocumentIndex(url)
    return FileDocumentIndex()