"""Runner: plan a goal, show the plan, ask, then run it with saving and a log.

All collaborators are passed in (planner, executor factory, store, ask, say),
so tests drive it with fakes and only __main__ touches Gemini and the terminal.
Nothing runs or is saved until the user answers yes to the plan preview.
"""
import json
from typing import Callable

from workflows.executor import EventFn, WorkflowExecutor
from workflows.models import TaskStatus, Workflow, WorkflowStatus
from workflows.planner import PlanError, Planner
from workflows.store import StoreError, WorkflowStore

MAX_SHOWN_CHARS = 300

Say = Callable[[str], None]
Ask = Callable[[str], str]
ExecutorFactory = Callable[[EventFn], WorkflowExecutor]


def _one_line(value: object, limit: int = MAX_SHOWN_CHARS) -> str:
    if isinstance(value, str):
        text = value
    else:
        try:
            text = json.dumps(value, ensure_ascii=False, default=str)
        except (TypeError, ValueError):
            text = str(value)
    text = " ".join(text.split())
    return text if len(text) <= limit else text[:limit] + "..."


def format_plan(workflow: Workflow) -> str:
    lines = [f"Plan for: {_one_line(workflow.goal, 200)}"]
    for number, task in enumerate(workflow.tasks, start=1):
        kind = f"tool {task.tool}" if task.tool else "model step"
        args = f" {_one_line(task.arguments, 120)}" if task.arguments else ""
        after = f" after {', '.join(task.depends_on)}" if task.depends_on else ""
        lines.append(f"  {number}. [{kind}]{args}{after} - {_one_line(task.description, 120)}")
    return "\n".join(lines)


def format_result(workflow: Workflow) -> str:
    lines = []
    for task in workflow.tasks:
        failed = task.status in (TaskStatus.FAILED, TaskStatus.SKIPPED, TaskStatus.CANCELLED)
        detail = task.error if failed and task.error else task.output
        shown = f" - {_one_line(detail)}" if detail not in (None, "") else ""
        lines.append(f"  {task.id}: {task.status.value}{shown}")
    lines.append(f"Workflow {workflow.id}: {workflow.status.value}")
    return "\n".join(lines)


def _confirmed(ask: Ask, prompt: str) -> bool:
    try:
        answer = ask(prompt)
    except (EOFError, KeyboardInterrupt):
        return False
    return isinstance(answer, str) and answer.strip().lower() in {"y", "yes"}


def _execute(
    workflow: Workflow, make_executor: ExecutorFactory, store: WorkflowStore, say: Say
) -> Workflow | None:
    try:
        store.save(workflow)
    except StoreError as e:
        say(f"Could not save the workflow, so it was not run: {e}")
        return None
    say(f"Running workflow {workflow.id} ...")
    executor = make_executor(store.listener(workflow))
    try:
        executor.run(workflow)
    except KeyboardInterrupt:
        say(
            "\nInterrupted. Progress is saved. "
            f"Resume with: python -m workflows --resume {workflow.id}"
        )
        return workflow
    try:
        store.save(workflow)
    except StoreError as e:
        say(f"Warning: could not save the final state: {e}")
    say(format_result(workflow))
    return workflow


def run_goal(
    goal: str,
    planner: Planner,
    make_executor: ExecutorFactory,
    store: WorkflowStore,
    ask: Ask = input,
    say: Say = print,
) -> Workflow | None:
    try:
        workflow = planner.plan(goal)
    except PlanError as e:
        say(f"Could not plan: {e}")
        return None
    say(format_plan(workflow))
    if not _confirmed(ask, "Run this plan? [y/N] "):
        say("Not run.")
        return None
    return _execute(workflow, make_executor, store, say)


def resume_workflow(
    workflow_id: str, make_executor: ExecutorFactory, store: WorkflowStore, say: Say = print
) -> Workflow | None:
    try:
        workflow = store.load(workflow_id)
    except StoreError as e:
        say(f"Could not resume: {e}")
        return None
    if workflow.status in (WorkflowStatus.SUCCEEDED, WorkflowStatus.CANCELLED):
        say(f"Workflow {workflow.id} is already {workflow.status.value}.")
        say(format_result(workflow))
        return workflow
    say(f"Resuming workflow {workflow.id} ...")
    return _execute(workflow, make_executor, store, say)


def list_runs(store: WorkflowStore, say: Say = print) -> None:
    ids = store.list_ids()
    if not ids:
        say("No saved workflows.")
        return
    for workflow_id in ids:
        try:
            workflow = store.load(workflow_id, resume=False)
        except StoreError:
            say(f"{workflow_id}  (unreadable)")
            continue
        say(f"{workflow_id}  {workflow.status.value}  {_one_line(workflow.goal, 60)}")