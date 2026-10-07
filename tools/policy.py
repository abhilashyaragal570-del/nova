"""Tool permission policy: decides whether a tool call may run.

Fails closed: anything unclear is refused. The policy never runs tools;
it only answers "allowed?" and gives a reason when the answer is no.
"""
import logging
from dataclasses import dataclass, field
from typing import Any, Callable

from tools.base import Tool

logger = logging.getLogger(__name__)

# (tool_name, arguments) -> True to approve. Anything else means "no".
ConfirmFn = Callable[[str, dict[str, Any]], bool]


@dataclass
class ToolPolicy:
    allowed: set[str] | None = None  # None = every registered tool is allowed
    blocked: set[str] = field(default_factory=set)
    confirm: ConfirmFn | None = None  # asked before any non-read-only tool

    def check(self, tool: Tool, arguments: dict[str, Any]) -> str | None:
        """Return None if the call may run, otherwise the reason it can't."""
        if tool.name in self.blocked:
            return f"Tool '{tool.name}' is blocked by policy"

        if self.allowed is not None and tool.name not in self.allowed:
            return f"Tool '{tool.name}' is not on the allowed list"

        if not tool.read_only:
            if self.confirm is None:
                return f"Tool '{tool.name}' needs user confirmation, but none is configured"
            try:
                approved = self.confirm(tool.name, arguments)
            except Exception:
                logger.exception("Confirmation handler failed for %s", tool.name)
                return f"Confirmation for '{tool.name}' failed, so it was not run"
            if approved is not True:
                return f"The user declined to run '{tool.name}'"

        return None