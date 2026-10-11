"""Adds saved long-term facts to a system prompt.

Never raises: if memory cannot be read, the chat simply starts without it.
"""
from typing import Any


def with_memory(system_prompt: str, store: Any) -> str:
    """Return the system prompt followed by the saved facts, if there are any."""
    try:
        block = store.prompt_block()
    except Exception:
        return system_prompt
    if not block:
        return system_prompt
    return f"{system_prompt}\n\n{block}"