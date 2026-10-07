"""Registry: finds tools by name and executes them safely."""
import logging
from typing import Any

from tools.base import Tool, ToolResult

logger = logging.getLogger(__name__)


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}

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

        try:
            logger.info("Running tool %s", name)
            return tool.run(**arguments)
        except Exception as e:  # tools must never crash Nova
            logger.exception("Tool %s failed", name)
            return ToolResult.failure(f"{type(e).__name__}: {e}")