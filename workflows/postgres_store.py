"""PostgreSQL version of WorkflowStore.

Same methods as workflows.store.WorkflowStore, so the runner and executor
don't change. Runs are rows in workflow_runs, events are rows in
workflow_events.
"""
import json
import logging
import time
from typing import Any

import psycopg
from psycopg.types.json import Jsonb

from workflows.models import Workflow
from workflows.store import StoreError, WorkflowStore, _check_id

logger = logging.getLogger(__name__)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS workflow_runs (
    id          TEXT PRIMARY KEY,
    data        JSONB NOT NULL,
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS workflow_events (
    seq          BIGSERIAL PRIMARY KEY,
    workflow_id  TEXT NOT NULL,
    ts           DOUBLE PRECISION NOT NULL,
    kind         TEXT NOT NULL,
    task         TEXT NOT NULL,
    detail       TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS workflow_events_workflow_idx
    ON workflow_events (workflow_id, seq);
"""


class PostgresWorkflowStore:
    # Same logic as the file store, so it is reused instead of copied.
    reset_interrupted = staticmethod(WorkflowStore.reset_interrupted)
    listener = WorkflowStore.listener

    def __init__(self, database_url: str) -> None:
        self.database_url = database_url
        try:
            with psycopg.connect(self.database_url) as conn:
                conn.execute(_SCHEMA)
        except psycopg.Error as e:
            raise StoreError(f"could not set up workflow tables: {type(e).__name__}") from None

    def save(self, workflow: Workflow) -> None:
        workflow_id = _check_id(workflow.id)
        try:
            data = workflow.to_dict()
            json.dumps(data)  # refuse anything that cannot be stored, like the file store
        except (TypeError, ValueError) as e:
            raise StoreError(f"workflow is not JSON-serializable: {e}") from None
        try:
            with psycopg.connect(self.database_url) as conn:
                conn.execute(
                    """
                    INSERT INTO workflow_runs (id, data, updated_at)
                    VALUES (%s, %s, now())
                    ON CONFLICT (id) DO UPDATE
                    SET data = EXCLUDED.data, updated_at = now()
                    """,
                    (workflow_id, Jsonb(data)),
                )
        except psycopg.Error as e:
            raise StoreError(f"could not save workflow: {type(e).__name__}") from None

    def load(self, workflow_id: str, resume: bool = True) -> Workflow:
        workflow_id = _check_id(workflow_id)
        try:
            with psycopg.connect(self.database_url) as conn:
                row = conn.execute(
                    "SELECT data FROM workflow_runs WHERE id = %s", (workflow_id,)
                ).fetchone()
        except psycopg.Error as e:
            raise StoreError(f"could not read workflow: {type(e).__name__}") from None
        if row is None:
            raise StoreError(f"no saved workflow {workflow_id!r}")
        try:
            workflow = Workflow.from_dict(row[0])
        except (KeyError, TypeError, ValueError) as e:
            raise StoreError(f"saved workflow is invalid: {e}") from None
        if resume:
            self.reset_interrupted(workflow)
        return workflow

    def list_ids(self) -> list[str]:
        try:
            with psycopg.connect(self.database_url) as conn:
                rows = conn.execute("SELECT id FROM workflow_runs ORDER BY id").fetchall()
        except psycopg.Error as e:
            raise StoreError(f"could not list workflows: {type(e).__name__}") from None
        return [r[0] for r in rows]

    def append_event(self, workflow_id: str, kind: str, task_id: str, detail: str = "") -> None:
        workflow_id = _check_id(workflow_id)
        try:
            with psycopg.connect(self.database_url) as conn:
                conn.execute(
                    "INSERT INTO workflow_events (workflow_id, ts, kind, task, detail) "
                    "VALUES (%s, %s, %s, %s, %s)",
                    (workflow_id, time.time(), kind, task_id, detail),
                )
        except psycopg.Error as e:
            logger.warning("could not write event log: %s", type(e).__name__)

    def read_events(self, workflow_id: str) -> list[dict[str, Any]]:
        workflow_id = _check_id(workflow_id)
        try:
            with psycopg.connect(self.database_url) as conn:
                rows = conn.execute(
                    "SELECT ts, kind, task, detail FROM workflow_events "
                    "WHERE workflow_id = %s ORDER BY seq",
                    (workflow_id,),
                ).fetchall()
        except psycopg.Error as e:
            raise StoreError(f"could not read events: {type(e).__name__}") from None
        return [{"ts": ts, "kind": kind, "task": task, "detail": detail} for ts, kind, task, detail in rows]