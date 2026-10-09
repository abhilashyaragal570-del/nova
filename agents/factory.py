"""Builds a Gemini chat for a specialized agent.

The client, model and source registry are passed in rather than imported, so
tests can use fakes and never touch the real API.
"""
from google.genai import types

from agents.definitions import AgentSpec, build_registry
from tools.gemini_adapter import to_gemini_tool
from tools.registry import ToolRegistry


def new_agent_chat(client, model, spec: AgentSpec, source: ToolRegistry, contents=None):
    """Return (chat, registry) for this agent.

    The chat is told about only the agent's tools, and the returned registry
    is the one run_turn must use, so a tool the agent was never given cannot
    be executed.
    """
    registry = build_registry(spec, source)
    gemini_tool = to_gemini_tool(registry)
    chat = client.chats.create(
        model=model,
        config=types.GenerateContentConfig(
            system_instruction=spec.system_prompt,
            tools=[gemini_tool] if gemini_tool else None,
        ),
        history=contents or [],
    )
    return chat, registry