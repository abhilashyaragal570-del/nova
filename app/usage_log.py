"""Writes one JSON line per chat turn: which tools ran, token usage and, when
the caller measured them, how long the turn took and how much of that was spent
waiting for the person to approve a tool.

Deliberately does not import config.settings, which raises an error when
GEMINI_API_KEY is missing. Its one optional setting, TOOL_LOG_PATH, is read
from the environment or from .env, and defaults to logs/tool_usage.jsonl.
When the log reaches MAX_LOG_BYTES, it is moved to <name>.1 (replacing any
older copy) and a fresh log is started.
Logging must never break a chat, so write errors are reported and swallowed.
"""
import json
import logging
import math
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SETTING_NAME = "TOOL_LOG_PATH"
DEFAULT_LOG_PATH = "logs/tool_usage.jsonl"
MAX_LOG_BYTES = 1_000_000


def _read_env_file(name: str, env_file: Path) -> str | None:
    """Return the value of NAME from a .env file, or None."""
    try:
        lines = env_file.read_text(encoding="utf-8").splitlines()
    except OSError:
        return None
    for line in lines:
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        if key.strip() == name:
            return value.strip().strip('"').strip("'") or None
    return None


def get_log_path(env_file: Path | None = None) -> Path:
    """Environment variable first, then .env, then the default."""
    env_file = env_file or PROJECT_ROOT / ".env"
    value = os.environ.get(SETTING_NAME) or _read_env_file(SETTING_NAME, env_file)
    path = Path(value or DEFAULT_LOG_PATH)
    return path if path.is_absolute() else PROJECT_ROOT / path


def _clean_seconds(value: Any) -> float | None:
    """A usable number of seconds, or None for anything else."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    if not math.isfinite(value) or value < 0:
        return None
    return round(float(value), 3)


def build_entry(
    result: Any,
    source: str,
    duration_seconds: Any = None,
    approval_wait_seconds: Any = None,
) -> dict:
    """Turn a TurnResult into a plain dict. Never includes message text."""
    entry = {
        "time": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "source": source,
        "tools": list(result.tools_used),
        "tool_calls": result.tool_calls,
        "hit_round_limit": result.hit_round_limit,
        "prompt_tokens": result.prompt_tokens,
        "reply_tokens": result.reply_tokens,
        "total_tokens": result.total_tokens,
    }
    duration = _clean_seconds(duration_seconds)
    if duration is not None:
        entry["duration_seconds"] = duration
    wait = _clean_seconds(approval_wait_seconds)
    if wait is not None:
        entry["approval_wait_seconds"] = wait
    return entry


def _rotate_if_needed(path: Path, max_bytes: int) -> None:
    """Move a full log to <name>.1, replacing any older copy."""
    if path.is_file() and path.stat().st_size >= max_bytes:
        os.replace(path, path.with_name(path.name + ".1"))


def log_turn(
    result: Any,
    source: str = "unknown",
    path: Path | None = None,
    max_bytes: int = MAX_LOG_BYTES,
    duration_seconds: Any = None,
    approval_wait_seconds: Any = None,
) -> bool:
    """Append one line for this turn. Returns True if it was written."""
    path = Path(path) if path else get_log_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        _rotate_if_needed(path, max_bytes)
        with path.open("a", encoding="utf-8") as f:
            f.write(
                json.dumps(
                    build_entry(
                        result, source, duration_seconds, approval_wait_seconds
                    )
                )
                + "\n"
            )
        return True
    except OSError as exc:
        logger.warning("Could not write tool usage log %s: %s", path, exc)
        return False