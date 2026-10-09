"""Pending tool approvals for the web chat.

The worker thread running a tool call blocks in confirm() until the
browser answers through resolve(), or the timeout passes. Fails closed:
only an explicit approval returns True.
"""
import json
import threading
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

    def confirm(self, tool_name: str, arguments: dict[str, Any]) -> bool:
        """Matches ToolPolicy's ConfirmFn. Blocks until answered or timed out."""
        pending = _Pending(tool_name, _summarize(arguments))
        approval_id = uuid.uuid4().hex
        with self._lock:
            self._pending[approval_id] = pending
        answered = pending.event.wait(self.timeout)
        with self._lock:
            self._pending.pop(approval_id, None)
        return answered and pending.approved is True

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