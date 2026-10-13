"""Writes one JSON line per workflow run to the same log as chat turns.

The line has source "workflow", how long the run took (workflow_seconds) and
how much of that was spent waiting for the person to approve a tool
(approval_wait_seconds). It uses its own key for the total, not
duration_seconds, so a long workflow never skews the chat latency numbers.

Never includes the goal text or task arguments. Logging must never break a
run, so write errors are reported and swallowed.
"""
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.usage_log import (
    MAX_LOG_BYTES,
    _clean_seconds,
    _rotate_if_needed,
    get_log_path,
)

logger = logging.getLogger(__name__)


def build_workflow_entry(
    workflow: Any,
    duration_seconds: Any = None,
    approval_wait_seconds: Any = None,
) -> dict:
    """Turn a finished Workflow into a plain dict."""
    tasks = list(workflow.tasks)
    entry = {
        "time": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "source": "workflow",
        "tools": [t.tool for t in tasks if t.tool and t.attempts],
        "tool_calls": sum(t.attempts for t in tasks if t.tool),
        "hit_round_limit": False,
        "prompt_tokens": 0,
        "reply_tokens": 0,
        "total_tokens": 0,
        "tasks": len(tasks),
        "status": workflow.status.value,
    }
    duration = _clean_seconds(duration_seconds)
    if duration is not None:
        entry["workflow_seconds"] = duration
    wait = _clean_seconds(approval_wait_seconds)
    if wait is not None:
        entry["approval_wait_seconds"] = wait
    return entry


def log_workflow(
    workflow: Any,
    duration_seconds: Any = None,
    approval_wait_seconds: Any = None,
    path: Path | None = None,
    max_bytes: int = MAX_LOG_BYTES,
) -> bool:
    """Append one line for this run. Returns True if it was written."""
    path = Path(path) if path else get_log_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        _rotate_if_needed(path, max_bytes)
        entry = build_workflow_entry(workflow, duration_seconds, approval_wait_seconds)
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry) + "\n")
        return True
    except OSError as exc:
        logger.warning("Could not write workflow log %s: %s", path, exc)
        return False