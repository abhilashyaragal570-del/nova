"""Registry: finds tools by name and executes them safely."""
import logging
import threading
from typing import Any, Callable

from tools.base import Tool, ToolResult
from tools.policy import ToolPolicy

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT_SECONDS = 30.0


class ToolTimeout(Exception):
    """Raised internally when a tool runs past its time limit."""


def _run_with_timeout(fn: Callable[[], Any], timeout: float | None) -> Any:
    """Run fn in a daemon thread and wait up to `timeout` seconds.

    Python cannot kill a thread, so a timed-out tool may keep running in
    the background. The caller stops waiting, which is what matters here.
    """
    if timeout is None:
        return fn()

    box: dict[str, Any] = {}

    def target() -> None:
        try:
            box["result"] = fn()
        except BaseException as e:  # handed back to the caller below
            box["error"] = e

    thread = threading.Thread(target=target, daemon=True)
    thread.start()
    thread.join(timeout)
    if thread.is_alive():
        raise ToolTimeout()
    if "error" in box:
        raise box["error"]
    return box["result"]


class ToolRegistry:
    def __init__(
        self,
        policy: ToolPolicy | None = None,
        default_timeout: float | None = DEFAULT_TIMEOUT_SECONDS,
    ) -> None:
        self._tools: dict[str, Tool] = {}
        self.policy = policy
        self.default_timeout = default_timeout

    def register(self, tool: Tool) -> None:
        if not tool.name:
            raise ValueError("Tool must have a name")
        if tool.name in self._tools:
            raise ValueError(f"Tool already registered: {tool.name}")
        self._tools[tool.name] = tool

    def get(self, name: str) -> Tool | None:
        return self._tools.get(name)

    def all(self) -> list[Tool]:
        return list(self._tools.values())

    def execute(self, name: str, arguments: dict[str, Any] | None = None) -> ToolResult:
        arguments = arguments or {}
        tool = self.get(name)
        if tool is None:
            return ToolResult.failure(f"Unknown tool: {name}")

        missing = [k for k in tool.parameters.get("required", []) if k not in arguments]
        if missing:
            return ToolResult.failure(f"Missing required arguments: {', '.join(missing)}")

        if self.policy is not None:
            reason = self.policy.check(tool, arguments)
            if reason is not None:
                logger.warning("Tool %s refused: %s", name, reason)
                return ToolResult.failure(reason)

        tool_timeout = getattr(tool, "timeout_seconds", None)
        timeout = tool_timeout if tool_timeout is not None else self.default_timeout

        try:
            logger.info("Running tool %s", name)
            return _run_with_timeout(lambda: tool.run(**arguments), timeout)
        except ToolTimeout:
            logger.warning("Tool %s timed out after %ss", name, timeout)
            return ToolResult.failure(f"Tool '{name}' timed out after {timeout:g} seconds")
        except Exception as e:  # tools must never crash Nova
            logger.exception("Tool %s failed", name)
            return ToolResult.failure(f"{type(e).__name__}: {e}")