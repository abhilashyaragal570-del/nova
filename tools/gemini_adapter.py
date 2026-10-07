"""Translate Nova tools into Gemini function declarations.

Kept separate from tools/base.py so tools stay independent of any LLM SDK.
"""
from google.genai import types

from tools.base import Tool
from tools.registry import ToolRegistry


def to_function_declaration(tool: Tool) -> types.FunctionDeclaration:
    """Convert one Tool into the format Gemini expects."""
    return types.FunctionDeclaration(
        name=tool.name,
        description=tool.description,
        parameters_json_schema=tool.parameters,
    )


def to_gemini_tool(registry: ToolRegistry) -> types.Tool | None:
    """Bundle every registered tool into one Gemini Tool object.

    Returns None when no tools are registered, so callers can skip it.
    """
    declarations = [to_function_declaration(t) for t in registry.all()]
    if not declarations:
        return None
    return types.Tool(function_declarations=declarations)