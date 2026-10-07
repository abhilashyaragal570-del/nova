"""Workflow state model: tasks, statuses, dependencies, and the rules for
moving between them.

Pure data and rules. No LLM, no tools, no network, no files, so every
behavior here is testable instantly. The executor uses these types; the
planner (later) must produce valid ones.
"""
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

MAX_TASKS = 50


class WorkflowError(ValueError):
    """Raised when a task or workflow is invalid."""


class InvalidTransition(WorkflowError):
    """Raised when a status change is not allowed."""


class TaskStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    SKIPPED = "skipped"
    CANCELLED = "cancelled"


class WorkflowStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


_ALLOWED_MOVES = {
    TaskStatus.PENDING: {TaskStatus.RUNNING, TaskStatus.SKIPPED, TaskStatus.CANCELLED},
    TaskStatus.RUNNING: {TaskStatus.SUCCEEDED, TaskStatus.FAILED, TaskStatus.CANCELLED},
    TaskStatus.FAILED: {TaskStatus.PENDING},  # only through retry()
    TaskStatus.SUCCEEDED: set(),
    TaskStatus.SKIPPED: set(),
    TaskStatus.CANCELLED: set(),
}

TASK_FINISHED = {
    TaskStatus.SUCCEEDED,
    TaskStatus.FAILED,
    TaskStatus.SKIPPED,
    TaskStatus.CANCELLED,
}


@dataclass
class Task:
    id: str
    description: str
    tool: str | None = None  # None = a step the model itself will do (later)
    arguments: dict[str, Any] = field(default_factory=dict)
    depends_on: tuple[str, ...] = ()
    max_attempts: int = 1
    status: TaskStatus = TaskStatus.PENDING
    output: Any = None
    error: str | None = None
    attempts: int = 0

    def __post_init__(self) -> None:
        if not isinstance(self.id, str) or not self.id.strip():
            raise WorkflowError("task id must be a non-empty string")
        if not isinstance(self.description, str) or not self.description.strip():
            raise WorkflowError(f"task {self.id!r} needs a description")
        if not isinstance(self.arguments, dict):
            raise WorkflowError(f"task {self.id!r}: arguments must be a dict")
        self.depends_on = tuple(self.depends_on)
        if self.id in self.depends_on:
            raise WorkflowError(f"task {self.id!r} cannot depend on itself")
        if len(set(self.depends_on)) != len(self.depends_on):
            raise WorkflowError(f"task {self.id!r} lists a dependency twice")
        if not isinstance(self.max_attempts, int) or self.max_attempts < 1:
            raise WorkflowError(f"task {self.id!r}: max_attempts must be at least 1")

    def _move(self, new: TaskStatus) -> None:
        if new not in _ALLOWED_MOVES[self.status]:
            raise InvalidTransition(
                f"task {self.id!r}: cannot go from {self.status.value} to {new.value}"
            )
        self.status = new

    def start(self) -> None:
        self._move(TaskStatus.RUNNING)
        self.attempts += 1
        self.error = None

    def succeed(self, output: Any) -> None:
        self._move(TaskStatus.SUCCEEDED)
        self.output = output
        self.error = None

    def fail(self, error: str) -> None:
        self._move(TaskStatus.FAILED)
        self.error = str(error)

    @property
    def can_retry(self) -> bool:
        return self.status is TaskStatus.FAILED and self.attempts < self.max_attempts

    def retry(self) -> None:
        if not self.can_retry:
            raise InvalidTransition(f"task {self.id!r} has no attempts left")
        self._move(TaskStatus.PENDING)

    def skip(self, reason: str) -> None:
        self._move(TaskStatus.SKIPPED)
        self.error = reason

    def cancel(self) -> None:
        self._move(TaskStatus.CANCELLED)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "description": self.description,
            "tool": self.tool,
            "arguments": dict(self.arguments),
            "depends_on": list(self.depends_on),
            "max_attempts": self.max_attempts,
            "status": self.status.value,
            "output": self.output,
            "error": self.error,
            "attempts": self.attempts,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Task":
        return cls(
            id=data["id"],
            description=data["description"],
            tool=data.get("tool"),
            arguments=data.get("arguments") or {},
            depends_on=tuple(data.get("depends_on") or ()),
            max_attempts=data.get("max_attempts", 1),
            status=TaskStatus(data.get("status", "pending")),
            output=data.get("output"),
            error=data.get("error"),
            attempts=data.get("attempts", 0),
        )


@dataclass
class Workflow:
    goal: str
    tasks: list[Task]
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    status: WorkflowStatus = WorkflowStatus.PENDING

    def __post_init__(self) -> None:
        if not isinstance(self.goal, str) or not self.goal.strip():
            raise WorkflowError("workflow needs a goal")
        if not self.tasks:
            raise WorkflowError("workflow needs at least one task")
        if len(self.tasks) > MAX_TASKS:
            raise WorkflowError(f"too many tasks (max {MAX_TASKS})")
        ids = [t.id for t in self.tasks]
        if len(set(ids)) != len(ids):
            raise WorkflowError("task ids must be unique")
        known = set(ids)
        for t in self.tasks:
            for dep in t.depends_on:
                if dep not in known:
                    raise WorkflowError(f"task {t.id!r} depends on unknown task {dep!r}")
        self._check_no_cycle()

    def _check_no_cycle(self) -> None:
        remaining = {t.id: set(t.depends_on) for t in self.tasks}
        while remaining:
            free = [i for i, deps in remaining.items() if not deps]
            if not free:
                raise WorkflowError("tasks contain a dependency cycle")
            for i in free:
                del remaining[i]
            for deps in remaining.values():
                deps.difference_update(free)

    def get(self, task_id: str) -> Task:
        for t in self.tasks:
            if t.id == task_id:
                return t
        raise WorkflowError(f"unknown task {task_id!r}")

    def ready_tasks(self) -> list[Task]:
        """Pending tasks whose dependencies have all succeeded."""
        done = {t.id for t in self.tasks if t.status is TaskStatus.SUCCEEDED}
        return [
            t
            for t in self.tasks
            if t.status is TaskStatus.PENDING and all(d in done for d in t.depends_on)
        ]

    def skip_dependents(self, failed_id: str) -> list[str]:
        """Skip every pending task that depends, directly or not, on failed_id."""
        blocked = {failed_id}
        skipped: list[str] = []
        changed = True
        while changed:
            changed = False
            for t in self.tasks:
                if t.status is TaskStatus.PENDING and any(d in blocked for d in t.depends_on):
                    t.skip(f"skipped because a dependency did not succeed ({failed_id})")
                    blocked.add(t.id)
                    skipped.append(t.id)
                    changed = True
        return skipped

    def cancel(self) -> None:
        """Cancel unfinished tasks. Finished tasks keep their results."""
        for t in self.tasks:
            if t.status in (TaskStatus.PENDING, TaskStatus.RUNNING):
                t.cancel()
        self.status = WorkflowStatus.CANCELLED

    def refresh_status(self) -> WorkflowStatus:
        """Work out the workflow status from its tasks and store it."""
        if self.status is WorkflowStatus.CANCELLED:
            return self.status
        states = [t.status for t in self.tasks]
        if all(s is TaskStatus.SUCCEEDED for s in states):
            self.status = WorkflowStatus.SUCCEEDED
        elif all(s in TASK_FINISHED for s in states):
            self.status = WorkflowStatus.FAILED
        elif all(s is TaskStatus.PENDING for s in states):
            self.status = WorkflowStatus.PENDING
        else:
            self.status = WorkflowStatus.RUNNING
        return self.status

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "goal": self.goal,
            "status": self.status.value,
            "tasks": [t.to_dict() for t in self.tasks],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Workflow":
        return cls(
            goal=data["goal"],
            tasks=[Task.from_dict(t) for t in data["tasks"]],
            id=data["id"],
            status=WorkflowStatus(data.get("status", "pending")),
        )