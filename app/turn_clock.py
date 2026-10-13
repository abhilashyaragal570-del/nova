"""Times a chat turn and the part of it spent waiting for the person.

Used by the terminal chat, where approvals are answered at the keyboard.
timed_confirm() wraps any confirm function and adds the time it takes to a
counter kept per thread. The code that runs a turn calls start_turn() before
it and end_turn() after it, and gets back the total time and the waiting time,
so the log can keep them apart.

Both use time.perf_counter(), so the waiting time can never be longer than
the turn itself.
"""
import threading
import time
from typing import Any, Callable

ConfirmFn = Callable[[str, dict[str, Any]], bool]

_local = threading.local()


def reset_wait() -> None:
    """Start counting from zero on the calling thread."""
    _local.waited = 0.0


def add_wait(seconds: float) -> None:
    _local.waited = getattr(_local, "waited", 0.0) + seconds


def take_wait() -> float:
    """Seconds the calling thread spent waiting since reset_wait(), then reset."""
    waited = getattr(_local, "waited", 0.0)
    _local.waited = 0.0
    return waited


def timed_confirm(confirm: ConfirmFn) -> ConfirmFn:
    """Return a confirm function that counts the time the person takes.

    The answer (or the error) from the wrapped function is passed through
    unchanged, so the policy still fails closed.
    """

    def wrapper(tool_name: str, arguments: dict[str, Any]) -> bool:
        started = time.perf_counter()
        try:
            return confirm(tool_name, arguments)
        finally:
            add_wait(time.perf_counter() - started)

    return wrapper


def start_turn() -> float:
    reset_wait()
    return time.perf_counter()


def end_turn(started: float) -> tuple[float, float]:
    """(total seconds, seconds spent waiting for approval)."""
    return time.perf_counter() - started, take_wait()