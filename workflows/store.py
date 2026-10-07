"""Workflow persistence: atomic JSON saves, an append-only event log, resume.

Storage sits behind this small class so PostgreSQL can replace it in
Phase 4 without touching the executor. Workflow ids become filenames, so
they are validated first (no path traversal).
"""
import json
import logging
import os
import re
import tempfile
import time
from pathlib import Path
from typing import Any

from workflows.models import Task, TaskStatus, Workflow, WorkflowError, WorkflowStatus

logger = logging.getLogger(__name__)

DEFAULT_DIR = Path("workflow_data")
_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


class StoreError(WorkflowError):
    """Raised when a workflow cannot be saved or loaded."""


def _check_id(workflow_id: Any) -> str:
    if not isinstance(workflow_id, str) or not _ID_RE.match(workflow_id):
        raise StoreError("invalid workflow id")
    return workflow_id


class WorkflowStore:
    def __init__(self, directory: Path | str = DEFAULT_DIR) -> None:
        self.directory = Path(directory)
        self._runs = self.directory / "runs"
        self._logs = self.directory / "logs"

    def _run_path(self, workflow_id: str) -> Path:
        return self._runs / f"{_check_id(workflow_id)}.json"

    def _log_path(self, workflow_id: str) -> Path:
        return self._logs / f"{_check_id(workflow_id)}.jsonl"

    def save(self, workflow: Workflow) -> Path:
        """Write the workflow atomically: temp file, then rename over the target."""
        path = self._run_path(workflow.id)
        try:
            text = json.dumps(workflow.to_dict(), indent=2, ensure_ascii=False)
        except (TypeError, ValueError) as e:
            raise StoreError(f"workflow is not JSON-serializable: {e}") from None
        try:
            self._runs.mkdir(parents=True, exist_ok=True)
            fd, tmp = tempfile.mkstemp(dir=self._runs, suffix=".tmp")
            try:
                with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
                    f.write(text)
                os.replace(tmp, path)
            except BaseException:
                Path(tmp).unlink(missing_ok=True)
                raise
        except OSError as e:
            raise StoreError(f"could not save workflow: {type(e).__name__}") from None
        return path

    def load(self, workflow_id: str, resume: bool = True) -> Workflow:
        path = self._run_path(workflow_id)
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            raise StoreError(f"no saved workflow {workflow_id!r}") from None
        except (OSError, ValueError) as e:
            raise StoreError(f"could not read workflow: {type(e).__name__}") from None
        try:
            workflow = Workflow.from_dict(data)
        except (KeyError, TypeError, ValueError) as e:
            raise StoreError(f"saved workflow is invalid: {e}") from None
        if resume:
            self.reset_interrupted(workflow)
        return workflow

    @staticmethod
    def reset_interrupted(workflow: Workflow) -> list[str]:
        """Tasks left 'running' by a crash go back to pending so a run can resume.

        Running tasks never finished, so their attempt is not counted.
        """
        reset = []
        for t in workflow.tasks:
            if t.status is TaskStatus.RUNNING:
                t.status = TaskStatus.PENDING
                t.attempts = max(0, t.attempts - 1)
                reset.append(t.id)
        if reset and workflow.status is WorkflowStatus.RUNNING:
            workflow.status = WorkflowStatus.PENDING
        return reset

    def list_ids(self) -> list[str]:
        if not self._runs.is_dir():
            return []
        return sorted(p.stem for p in self._runs.glob("*.json") if _ID_RE.match(p.stem))

    def append_event(self, workflow_id: str, kind: str, task_id: str, detail: str = "") -> None:
        record = {"ts": time.time(), "kind": kind, "task": task_id, "detail": detail}
        try:
            self._logs.mkdir(parents=True, exist_ok=True)
            with open(self._log_path(workflow_id), "a", encoding="utf-8", newline="\n") as f:
                f.write(json.dumps(record, ensure_ascii=False) + "\n")
        except OSError as e:
            logger.warning("could not write event log: %s", type(e).__name__)

    def read_events(self, workflow_id: str) -> list[dict[str, Any]]:
        path = self._log_path(workflow_id)
        if not path.is_file():
            return []
        events = []
        for line in path.read_text(encoding="utf-8").splitlines():
            try:
                events.append(json.loads(line))
            except ValueError:
                continue  # skip a damaged line, keep the rest
        return events

    def listener(self, workflow: Workflow):
        """An on_event callback for the executor: logs the event, then saves state."""

        def on_event(kind: str, task_id: str, detail: str) -> None:
            self.append_event(workflow.id, kind, task_id, detail)
            workflow.refresh_status()
            try:
                self.save(workflow)
            except StoreError:
                logger.exception("could not save workflow %s", workflow.id)

        return on_event