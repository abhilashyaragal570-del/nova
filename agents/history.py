"""Saved conversations for specialized agents.

Each agent has one stable conversation id derived from its name, so a session
resumes where the last one ended. The ids are valid for ConversationStore and
never equal MAIN_ID, so the main chat history is never touched.
"""
import hashlib

from google.genai import types

from agents.definitions import AgentSpec


def conversation_id(agent_name: str) -> str:
    digest = hashlib.sha256(f"nova-agent:{agent_name}".encode("utf-8")).hexdigest()
    return digest[:12]


def conversation_title(spec: AgentSpec) -> str:
    return f"Agent: {spec.name}"


def load_messages(store, spec: AgentSpec) -> list:
    data = store.load(conversation_id(spec.name))
    return data["messages"] if data else []


def save_messages(store, spec: AgentSpec, messages: list) -> None:
    store.save(conversation_id(spec.name), conversation_title(spec), messages)


def clear_messages(store, spec: AgentSpec) -> None:
    store.delete(conversation_id(spec.name))


def to_contents(messages: list) -> list:
    """Saved messages -> Gemini history, same shape as app.chat.to_contents."""
    return [
        types.Content(role=m["role"], parts=[types.Part(text=m["text"])])
        for m in messages
    ]