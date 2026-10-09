"""Runs one workflow at a time for the web app.

Planning and running happen in background threads, so a web request never
blocks. Nothing is saved or run until the plan is approved, like the terminal
runner. Tool approvals (writes, API calls) still go through the registry's
policy, so they show the same Approve / Deny cards as chat.

All collaborators are passed in, so tests use fakes and never call Gemini.
"""
import logging
import threading
import uuid
from typing import Any, Callable

from workflows.models import WorkflowStatus
from workflows.planner import PlanError
from workflows.runner import _one_line, format_plan, format_result
from workflows.store import StoreError

logger = logging.getLogger(__name__)

PLANNING = "planning"
AWAITING = "awaiting_approval"
RUNNING = "running"
DONE = "done"
ERROR = "error"
DECLINED = "declined"
CANCELLED = "cancelled"
ACTIVE = {PLANNING, RUNNING}
_UNFINISHED_TASK = {"failed", "skipped", "cancelled"}


class Busy(Exception):
    """Another workflow is planning or running."""


class _Run:
    def __init__(self, goal: str, write_tools: bool) -> None:
        self.id = uuid.uuid4().hex[:12]
        self.goal = goal
        self.write_tools = write_tools
        self.state = PLANNING
        self.workflow = None
        self.plan = ""
        self.error = ""
        self.cancel_event = threading.Event()


class WorkflowManager:
    def __init__(
        self,
        make_planner: Callable[[bool], Any],
        make_executor: Callable[[Callable, threading.Event], Any],
        make_store: Callable[[], Any],
    ) -> None:
        self._make_planner = make_planner
        self._make_executor = make_executor
        self._make_store = make_store
        self._store = None
        self._lock = threading.Lock()
        self._run: _Run | None = None

    def store(self):
        if self._store is None:  # created on first use, so importing never connects
            self._store = self._make_store()
        return self._store

    def _check_free(self) -> None:
        with self._lock:
            if self._run is not None and self._run.state in ACTIVE:
                raise Busy("a workflow is already planning or running")

    def _finish(self, run: _Run, state: str, error: str = "") -> None:
        with self._lock:
            run.state = state
            run.error = error

    # ---- starting ----

    def start(self, goal: str, write_tools: bool = False) -> str:
        goal = goal.strip() if isinstance(goal, str) else ""
        if not goal:
            raise ValueError("goal is empty")
        run = _Run(goal, bool(write_tools))
        with self._lock:
            if self._run is not None and self._run.state in ACTIVE:
                raise Busy("a workflow is already planning or running")
            self._run = run
        threading.Thread(target=self._plan, args=(run,), daemon=True).start()
        return run.id

    def _plan(self, run: _Run) -> None:
        try:
            workflow = self._make_planner(run.write_tools).plan(run.goal)
        except PlanError as e:
            self._finish(run, ERROR, f"Could not plan: {e}")
            return
        except Exception:
            logger.exception("planning failed")
            self._finish(run, ERROR, "Could not plan: unexpected error")
            return
        with self._lock:
            if run.cancel_event.is_set():
                run.state = CANCELLED
                return
            run.workflow = workflow
            run.plan = format_plan(workflow)
            run.state = AWAITING

    def resume(self, workflow_id: str) -> str:
        self._check_free()
        workflow = self.store().load(workflow_id)  # may raise StoreError
        if workflow.status in (WorkflowStatus.SUCCEEDED, WorkflowStatus.CANCELLED):
            raise ValueError(f"workflow is already {workflow.status.value}")
        run = _Run(workflow.goal, False)
        run.workflow = workflow
        run.plan = format_plan(workflow)
        run.state = RUNNING
        with self._lock:
            if self._run is not None and self._run.state in ACTIVE:
                raise Busy("a workflow is already planning or running")
            self._run = run
        threading.Thread(target=self._execute, args=(run,), daemon=True).start()
        return run.id

    # ---- answering the plan ----

    def approve(self, run_id: str, approved: bool) -> bool:
        """Answer the plan preview. False if there is no plan waiting under this id."""
        with self._lock:
            run = self._run
            if run is None or run.id != run_id or run.state != AWAITING:
                return False
            if approved is not True:
                run.state = DECLINED
                return True
            run.state = RUNNING
        threading.Thread(target=self._execute, args=(run,), daemon=True).start()
        return True

    def cancel(self, run_id: str) -> bool:
        with self._lock:
            run = self._run
            if run is None or run.id != run_id:
                return False
            if run.state == AWAITING:
                run.state = DECLINED
                return True
            if run.state in ACTIVE:
                run.cancel_event.set()
                return True
            return False

    # ---- running ----

    def _execute(self, run: _Run) -> None:
        workflow = run.workflow
        try:
            store = self.store()
            store.save(workflow)
        except StoreError as e:
            self._finish(run, ERROR, f"Could not save the workflow, so it was not run: {e}")
            return
        except Exception:
            logger.exception("could not open the workflow store")
            self._finish(run, ERROR, "Could not save the workflow, so it was not run.")
            return
        try:
            executor = self._make_executor(store.listener(workflow), run.cancel_event)
            executor.run(workflow)
        except Exception:
            logger.exception("workflow %s stopped unexpectedly", workflow.id)
            self._finish(
                run, ERROR, "The workflow stopped unexpectedly. Progress is saved; you can resume it."
            )
            return
        warning = ""
        try:
            store.save(workflow)
        except StoreError as e:
            warning = f"Could not save the final state: {e}"
        state = CANCELLED if workflow.status is WorkflowStatus.CANCELLED else DONE
        self._finish(run, state, warning)

    # ---- reading ----

    def snapshot(self, run_id: str | None = None) -> dict[str, Any] | None:
        """The current run as plain data for the browser, or None if there is none."""
        with self._lock:
            run = self._run
            if run is None or (run_id is not None and run.id != run_id):
                return None
            state = run.state
            data: dict[str, Any] = {
                "id": run.id,
                "state": state,
                "goal": run.goal,
                "plan": run.plan,
                "error": run.error,
                "tasks": [],
                "result": "",
            }
            workflow = run.workflow
        if workflow is not None:
            data["workflow_id"] = workflow.id
            data["workflow_status"] = workflow.status.value
            for t in list(workflow.tasks):
                detail = t.error if t.status.value in _UNFINISHED_TASK else t.output
                data["tasks"].append(
                    {
                        "id": t.id,
                        "description": _one_line(t.description, 120),
                        "tool": t.tool,
                        "status": t.status.value,
                        "detail": _one_line(detail) if detail not in (None, "") else "",
                    }
                )
            if state in (DONE, CANCELLED):
                data["result"] = format_result(workflow)
        return data

    def list_saved(self) -> list[dict[str, str]]:
        store = self.store()
        items = []
        for workflow_id in store.list_ids():
            try:
                workflow = store.load(workflow_id, resume=False)
            except StoreError:
                items.append({"id": workflow_id, "status": "unreadable", "goal": ""})
                continue
            items.append(
                {
                    "id": workflow_id,
                    "status": workflow.status.value,
                    "goal": _one_line(workflow.goal, 60),
                }
            )
        return items