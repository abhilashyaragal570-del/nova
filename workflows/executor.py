"""Workflow executor: runs a Workflow's tasks through the tool registry.

Every tool call goes through registry.execute(), so the permission policy,
confirmation prompts, and timeouts apply to workflows exactly as they do in
chat. A task with no tool is a model step: the injected model function does
it, seeing only the results of the tasks it depends on. A call the policy
refused (for example, the user said no) is never retried. The executor never
raises for a task problem; it records the failure.
"""
import logging
import threading
import time
from typing import Any, Callable

from tools.registry import ToolRegistry
from workflows.model_step import build_model_prompt
from workflows.models import Task, TaskStatus, Workflow, WorkflowStatus

logger = logging.getLogger(__name__)

BACKOFF_BASE_SECONDS = 1.0
BACKOFF_FACTOR = 2.0
BACKOFF_CAP_SECONDS = 30.0

# (kind, task_id, detail). kind is one of:
# start, succeed, retry, fail, skip, cancel, timeout
EventFn = Callable[[str, str, str], None]


def backoff_delay(
    attempt: int,
    base: float = BACKOFF_BASE_SECONDS,
    factor: float = BACKOFF_FACTOR,
    cap: float = BACKOFF_CAP_SECONDS,
) -> float:
    """Seconds to wait after failed attempt number `attempt` (1-based)."""
    if attempt < 1 or base <= 0:
        return 0.0
    return min(cap, base * (factor ** (attempt - 1)))


class WorkflowExecutor:
    def __init__(
        self,
        registry: ToolRegistry,
        on_event: EventFn | None = None,
        should_cancel: Callable[[], bool] | None = None,
        cancel_event: threading.Event | None = None,
        backoff_base: float = BACKOFF_BASE_SECONDS,
        deadline_seconds: float | None = None,
        sleep: Callable[[float], bool] | None = None,
        now: Callable[[], float] = time.monotonic,
        model: Callable[[str], str] | None = None,
    ) -> None:
        self.registry = registry
        self.on_event = on_event
        self.should_cancel = should_cancel
        self.cancel_event = cancel_event
        self.backoff_base = backoff_base
        self.deadline_seconds = deadline_seconds
        self.model = model
        self._now = now
        self._refused = False  # NEW (Step 8): did the last task end in a policy refusal?
        # A sleeper returns True if it was interrupted by cancellation.
        self._sleep = sleep or self._interruptible_sleep

    def _interruptible_sleep(self, seconds: float) -> bool:
        if seconds <= 0:
            return False
        if self.cancel_event is not None:
            return self.cancel_event.wait(seconds)
        time.sleep(seconds)
        return False

    def _emit(self, kind: str, task_id: str, detail: str = "") -> None:
        logger.info("workflow event: %s %s %s", kind, task_id, detail)
        if self.on_event is not None:
            try:
                self.on_event(kind, task_id, detail)
            except Exception:  # a broken listener must not break the run
                logger.exception("workflow event handler failed")

    def _cancelled(self) -> bool:
        if self.cancel_event is not None and self.cancel_event.is_set():
            return True
        if self.should_cancel is None:
            return False
        try:
            return bool(self.should_cancel())
        except Exception:
            logger.exception("should_cancel failed; stopping to be safe")
            return True

    def _run_model_task(
        self, task: Task, workflow: Workflow | None
    ) -> tuple[bool, Any, str | None]:
        """A step with no tool: the model does it, seeing only its dependencies' results."""
        if self.model is None:
            return False, None, "task has no tool assigned"
        try:
            text = self.model(build_model_prompt(task, workflow))
        except Exception as e:  # model calls fail in many ways; record, never raise
            logger.exception("model step failed for task %s", task.id)
            return False, None, f"model call failed: {type(e).__name__}"
        if not isinstance(text, str) or not text.strip():
            return False, None, "model returned no text"
        return True, text.strip(), None

    def _run_task(
        self, task: Task, workflow: Workflow | None = None
    ) -> tuple[bool, Any, str | None]:
        """Run one task. Returns (ok, output, error). Never raises."""
        self._refused = False  # NEW (Step 8)
        if task.tool is None:
            return self._run_model_task(task, workflow)
        try:
            result = self.registry.execute(task.tool, dict(task.arguments))
        except Exception as e:  # registry should not raise, but never trust it
            logger.exception("registry raised for task %s", task.id)
            return False, None, f"{type(e).__name__}: {e}"
        if result.ok:
            return True, result.output, None
        self._refused = getattr(result, "refused", False) is True  # NEW (Step 8)
        return False, None, result.error or "tool failed"

    def _stop(self, workflow: Workflow, kind: str, detail: str) -> Workflow:
        workflow.cancel()
        self._emit(kind, "-", detail)
        return workflow

    def run(self, workflow: Workflow) -> Workflow:
        if workflow.status in (WorkflowStatus.CANCELLED, WorkflowStatus.SUCCEEDED):
            return workflow

        started = self._now()

        def out_of_time() -> bool:
            return (
                self.deadline_seconds is not None
                and self._now() - started >= self.deadline_seconds
            )

        while True:
            if self._cancelled():
                return self._stop(workflow, "cancel", "workflow cancelled")
            if out_of_time():
                return self._stop(workflow, "timeout", "workflow deadline reached")

            ready = workflow.ready_tasks()
            if not ready:
                break

            task = ready[0]  # one at a time, in list order
            task.start()
            self._emit("start", task.id, f"attempt {task.attempts}/{task.max_attempts}")
            ok, output, error = self._run_task(task, workflow)

            if ok:
                task.succeed(output)
                self._emit("succeed", task.id)
                continue

            task.fail(error or "tool failed")
            if task.can_retry and not self._refused:  # NEW (Step 8): a "no" is final
                delay = backoff_delay(task.attempts, base=self.backoff_base)
                self._emit("retry", task.id, f"{task.error} (waiting {delay:g}s)")
                task.retry()
                if self._sleep(delay):
                    return self._stop(workflow, "cancel", "cancelled while waiting to retry")
                continue

            self._emit("fail", task.id, task.error or "")
            for skipped_id in workflow.skip_dependents(task.id):
                self._emit("skip", skipped_id, f"depends on {task.id}")

        workflow.refresh_status()
        return workflow