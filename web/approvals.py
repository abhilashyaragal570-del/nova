"""Pending tool approvals for the web chat.

The worker thread running a tool call blocks in confirm() until the
browser answers through resolve(), or the timeout passes. Fails closed:
only an explicit approval returns True.

confirm() also adds the time it spent waiting to a counter kept per thread.
The code that times a chat turn calls reset_wait() before the turn and
take_wait() after it, so the turn's latency can leave out the time the person
took to click Approve or Deny.

The wait is measured with time.perf_counter(), the same clock the turn timer
uses, so a turn's waiting time can never be longer than the turn itself.
"""
import json
import threading
import time
import uuid
from typing import Any

DEFAULT_TIMEOUT_SECONDS = 60.0
MAX_SUMMARY_CHARS = 1000


def _summarize(arguments: dict[str, Any]) -> str:
    try:
        text = json.dumps(arguments, ensure_ascii=False, default=str, indent=2)
    except Exception:
        text = repr(arguments)
    if len(text) > MAX_SUMMARY_CHARS:
        text = text[:MAX_SUMMARY_CHARS] + "\n... (truncated)"
    return text


class _Pending:
    def __init__(self, tool: str, summary: str) -> None:
        self.tool = tool
        self.summary = summary
        self.event = threading.Event()
        self.approved = False


class ApprovalBroker:
    def __init__(self, timeout: float = DEFAULT_TIMEOUT_SECONDS) -> None:
        self.timeout = timeout
        self._lock = threading.Lock()
        self._pending: dict[str, _Pending] = {}
        # Seconds this thread has spent waiting in confirm() since reset_wait().
        self._local = threading.local()

    def confirm(self, tool_name: str, arguments: dict[str, Any]) -> bool:
        """Matches ToolPolicy's ConfirmFn. Blocks until answered or timed out."""
        pending = _Pending(tool_name, _summarize(arguments))
        approval_id = uuid.uuid4().hex
        with self._lock:
            self._pending[approval_id] = pending
        started = time.perf_counter()
        answered = pending.event.wait(self.timeout)
        self._add_wait(time.perf_counter() - started)
        with self._lock:
            self._pending.pop(approval_id, None)
        return answered and pending.approved is True

    def _add_wait(self, seconds: float) -> None:
        self._local.waited = getattr(self._local, "waited", 0.0) + seconds

    def reset_wait(self) -> None:
        """Start counting from zero on the calling thread."""
        self._local.waited = 0.0

    def take_wait(self) -> float:
        """Seconds the calling thread spent waiting since reset_wait(), then reset."""
        waited = getattr(self._local, "waited", 0.0)
        self._local.waited = 0.0
        return waited

    def list_pending(self) -> list[dict[str, str]]:
        with self._lock:
            return [
                {"id": i, "tool": p.tool, "arguments": p.summary}
                for i, p in self._pending.items()
            ]

    def resolve(self, approval_id: str, approved: bool) -> bool:
        """Answer one pending approval. False if the id is unknown or already used."""
        with self._lock:
            pending = self._pending.pop(approval_id, None)
        if pending is None:
            return False
        pending.approved = approved is True
        pending.event.set()
        return True