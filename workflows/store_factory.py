"""Pick the workflow store: PostgreSQL if DATABASE_URL is set, else files."""
import os

from dotenv import load_dotenv

from workflows.store import WorkflowStore


def create_workflow_store():
    load_dotenv()
    url = os.environ.get("DATABASE_URL")
    if url:
        from workflows.postgres_store import PostgresWorkflowStore

        return PostgresWorkflowStore(url)
    return WorkflowStore()