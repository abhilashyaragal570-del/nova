"""Tool-calling loop: runs tools Gemini asks for and feeds results back.

Takes any object with send_message_stream(), so it can be tested with a
fake chat and no real API calls.
"""
import logging
from dataclasses import dataclass
from typing import Any, Callable

from google.genai import types

from tools.registry import ToolRegistry

logger = logging.getLogger(__name__)

MAX_TOOL_ROUNDS = 5
LIMIT_MESSAGE = "Tool call limit reached. Answer with the information you already have."


@dataclass
class TurnResult:
    reply: str = ""
    prompt_tokens: int = 0
    reply_tokens: int = 0
    total_tokens: int = 0
    tool_calls: int = 0
    hit_round_limit: bool = False


def _response_part(name: str, response: dict) -> types.Part:
    return types.Part.from_function_response(name=name, response=response)


def _run_call(registry: ToolRegistry, call: Any) -> types.Part:
    """Execute one function call and wrap the outcome for Gemini."""
    result = registry.execute(call.name, dict(call.args or {}))
    if result.ok:
        return _response_part(call.name, {"result": result.output})
    return _response_part(call.name, {"error": result.error})


def run_turn(
    chat: Any,
    user_input: str,
    registry: ToolRegistry,
    on_text: Callable[[str], None] | None = None,
    max_rounds: int = MAX_TOOL_ROUNDS,
) -> TurnResult:
    result = TurnResult()
    message: Any = user_input
    rounds = 0
    limit_reached = False

    while True:
        calls: list = []
        usage = None
        for chunk in chat.send_message_stream(message):
            text = getattr(chunk, "text", None)
            if text:
                result.reply += text
                if on_text:
                    on_text(text)
            calls.extend(getattr(chunk, "function_calls", None) or [])
            if getattr(chunk, "usage_metadata", None):
                usage = chunk.usage_metadata

        if usage:
            result.prompt_tokens += usage.prompt_token_count or 0
            result.reply_tokens += usage.candidates_token_count or 0
            result.total_tokens += usage.total_token_count or 0

        if not calls:
            break
        if limit_reached:  # told to stop, still asked for tools: give up
            break

        if rounds >= max_rounds:
            limit_reached = True
            result.hit_round_limit = True
            logger.warning("Tool round limit (%d) reached", max_rounds)
            message = [_response_part(c.name, {"error": LIMIT_MESSAGE}) for c in calls]
        else:
            rounds += 1
            result.tool_calls += len(calls)
            message = [_run_call(registry, c) for c in calls]

    return result