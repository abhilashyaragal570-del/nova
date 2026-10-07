"""Terminal confirmation prompt for tools that change things.

Shows the real arguments, defaults to "no", and treats any problem
(Ctrl+C, closed input, odd answers) as a refusal.
"""
from typing import Any, Callable

MAX_PREVIEW_CHARS = 200
YES_ANSWERS = {"y", "yes"}


def _preview(value: Any) -> str:
    """Show a value safely: repr() makes control characters visible."""
    text = repr(value)
    if len(text) > MAX_PREVIEW_CHARS:
        extra = len(text) - MAX_PREVIEW_CHARS
        text = text[:MAX_PREVIEW_CHARS] + f"... (+{extra} more characters)"
    return text


def confirm_in_terminal(
    name: str,
    arguments: dict[str, Any],
    input_fn: Callable[[str], str] = input,
    output_fn: Callable[[str], Any] = print,
) -> bool:
    """Ask the user to approve a tool call. Returns True only for y / yes."""
    output_fn(f"\n[Nova wants to run '{name}']")
    for key, value in arguments.items():
        output_fn(f"  {key}: {_preview(value)}")
    try:
        answer = input_fn("Allow? [y/N] ")
    except (EOFError, KeyboardInterrupt):
        output_fn("")
        return False
    return isinstance(answer, str) and answer.strip().lower() in YES_ANSWERS