"""Base types for Nova tools. Deliberately independent of any LLM SDK."""
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ToolResult:
    """What every tool returns. Never raise to the model; return a failure."""
    ok: bool
    output: Any = None
    error: str | None = None
    refused: bool = False  # NEW: the policy said no; retrying will not change that

    @classmethod
    def success(cls, output: Any) -> "ToolResult":
        return cls(ok=True, output=output)

    @classmethod
    def failure(cls, error: str) -> "ToolResult":
        return cls(ok=False, error=error)

    @classmethod
    def refusal(cls, reason: str) -> "ToolResult":  # NEW
        return cls(ok=False, error=reason, refused=True)


class Tool(ABC):
    """Subclass this to add a tool."""
    name: str = ""
    description: str = ""
    # JSON-schema style description of the arguments.
    parameters: dict = {"type": "object", "properties": {}, "required": []}
    read_only: bool = True  # used later for permissions

    @abstractmethod
    def run(self, **kwargs: Any) -> ToolResult:
        ...