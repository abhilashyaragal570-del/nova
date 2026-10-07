"""Terminal confirmation prompt for tools that change things.

Shows the real arguments, defaults to "no", and treats any problem
(Ctrl+C, closed input, odd answers) as a refusal. Warns loudly when
write_file is about to replace a file that already exists.
"""
from pathlib import Path
from typing import Any, Callable

MAX_PREVIEW_CHARS = 200
YES_ANSWERS = {"y", "yes"}
DEFAULT_WORKSPACE = Path("workspace")


def _preview(value: Any) -> str:
    """Show a value safely: repr() makes control characters visible."""
    text = repr(value)
    if len(text) > MAX_PREVIEW_CHARS:
        extra = len(text) - MAX_PREVIEW_CHARS
        text = text[:MAX_PREVIEW_CHARS] + f"... (+{extra} more characters)"
    return text


def _overwrite_warning(
    name: str, arguments: dict[str, Any], workspace: Path
) -> str | None:
    """Return a warning if this call would replace an existing file, else None."""
    if name != "write_file" or arguments.get("overwrite") is not True:
        return None
    path = arguments.get("path")
    if not isinstance(path, str) or not path.strip():
        return None
    try:
        exists = (Path(workspace) / path.strip()).exists()
    except (OSError, ValueError):
        return None
    if not exists:
        return None
    return f"  !! WARNING: this will REPLACE the existing file {path.strip()!r}"


def confirm_in_terminal(
    name: str,
    arguments: dict[str, Any],
    input_fn: Callable[[str], str] = input,
    output_fn: Callable[[str], Any] = print,
    workspace: Path | str = DEFAULT_WORKSPACE,
) -> bool:
    """Ask the user to approve a tool call. Returns True only for y / yes."""
    output_fn(f"\n[Nova wants to run '{name}']")
    for key, value in arguments.items():
        output_fn(f"  {key}: {_preview(value)}")
    warning = _overwrite_warning(name, arguments, Path(workspace))
    if warning:
        output_fn(warning)
    try:
        answer = input_fn("Allow? [y/N] ")
    except (EOFError, KeyboardInterrupt):
        output_fn("")
        return False
    return isinstance(answer, str) and answer.strip().lower() in YES_ANSWERS