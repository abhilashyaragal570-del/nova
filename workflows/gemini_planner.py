"""Glue between the planner and the real world: the tool registry and Gemini.

Importing app.llm creates the Gemini client, so it is imported lazily and
only when no model function is passed in. Tests pass a fake and never touch it.
Until approval checkpoints exist, only read-only tools are offered to the planner.
"""
from typing import Any, Callable

from tools.registry import ToolRegistry
from workflows.critic import make_critic  # NEW (Step 9)
from workflows.planner import Planner

_DESCRIPTION_CHARS = 80


def describe_tool(tool: Any) -> str:
    """One line for the prompt: a short description plus the argument names."""
    text = " ".join(str(getattr(tool, "description", "") or "").split())[:_DESCRIPTION_CHARS]
    params = getattr(tool, "parameters", None)
    props = params.get("properties") if isinstance(params, dict) else None
    if isinstance(props, dict) and props:
        required = set(params.get("required") or [])
        names = ", ".join(f"{n} (required)" if n in required else str(n) for n in props)
        text = f"{text} Arguments: {names}".strip()
    return text or "(no description)"


def tool_descriptions(registry: ToolRegistry, read_only_only: bool = True) -> dict[str, str]:
    return {
        tool.name: describe_tool(tool)
        for tool in registry.all()
        if not read_only_only or getattr(tool, "read_only", False)
    }


def make_planner(
    registry: ToolRegistry,
    generate: Callable[[str], str] | None = None,
    read_only_only: bool = True,
    retries: int = 1,
    critic: bool = False,  # NEW (Step 9): one extra model call per plan
) -> Planner:
    if generate is None:
        from app.llm import ask  # lazy: importing it creates the Gemini client

        generate = ask
    review = make_critic(generate) if critic else None  # NEW (Step 9)
    return Planner(
        generate, tool_descriptions(registry, read_only_only), retries=retries, critic=review
    )