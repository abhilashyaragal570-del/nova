"""Workflow executor: runs a Workflow's tasks through the tool registry.

Every tool call goes through registry.execute(), so the permission policy,
confirmation prompts, and timeouts apply to workflows exactly as they do in
chat. The executor never raises for a task problem; it records the failure.
"""
import logging
from typing import Any, Callable

from tools.registry import ToolRegistry
from workflows.models import Task, TaskStatus, Workflow, WorkflowStatus

logger = logging.getLogger(__name__)

# (kind, task_id, detail). kind is one of: start, succeed, retry, fail, skip, cancel
EventFn = Callable[[str, str, str], None]


class WorkflowExecutor:
    def __init__(
        self,
        registry: ToolRegistry,
        on_event: EventFn | None = None,
        should_cancel: Callable[[], bool] | None = None,
    ) -> None:
        self.registry = registry
        self.on_event = on_event
        self.should_cancel = should_cancel

    def _emit(self, kind: str, task_id: str, detail: str = "") -> None:
        logger.info("workflow event: %s %s %s", kind, task_id, detail)
        if self.on_event is not None:
            try:
                self.on_event(kind, task_id, detail)
            except Exception:  # a broken listener must not break the run
                logger.exception("workflow event handler failed")

    def _cancelled(self) -> bool:
        if self.should_cancel is None:
            return False
        try:
            return bool(self.should_cancel())
        except Exception:
            logger.exception("should_cancel failed; stopping to be safe")
            return True

    def _run_task(self, task: Task) -> tuple[bool, Any, str | None]:
        """Run one task. Returns (ok, output, error). Never raises."""
        if task.tool is None:
            return False, None, "task has no tool assigned"
        try:
            result = self.registry.execute(task.tool, dict(task.arguments))
        except Exception as e:  # registry should not raise, but never trust it
            logger.exception("registry raised for task %s", task.id)
            return False, None, f"{type(e).__name__}: {e}"
        if result.ok:
            return True, result.output, None
        return False, None, result.error or "tool failed"

    def run(self, workflow: Workflow) -> Workflow:
        if workflow.status in (WorkflowStatus.CANCELLED, WorkflowStatus.SUCCEEDED):
            return workflow

        while True:
            if self._cancelled():
                workflow.cancel()
                self._emit("cancel", "-", "workflow cancelled")
                return workflow

            ready = workflow.ready_tasks()
            if not ready:
                break

            task = ready[0]  # one at a time, in list order
            task.start()
            self._emit("start", task.id, f"attempt {task.attempts}/{task.max_attempts}")
            ok, output, error = self._run_task(task)

            if ok:
                task.succeed(output)
                self._emit("succeed", task.id)
                continue

            task.fail(error or "tool failed")
            if task.can_retry:
                self._emit("retry", task.id, task.error or "")
                task.retry()
                continue

            self._emit("fail", task.id, task.error or "")
            for skipped_id in workflow.skip_dependents(task.id):
                self._emit("skip", skipped_id, f"depends on {task.id}")

        workflow.refresh_status()
        return workflow