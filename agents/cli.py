"""Run a specialized agent from inside the normal terminal chat (/agent)."""
from agents.definitions import AgentError, get_agent, list_agents


def agent_menu() -> str:
    lines = ["Agents (use /agent <name>):"]
    for spec in list_agents():
        lines.append(f"  {spec.name:<12} {spec.description}")
    return "\n".join(lines) + "\n"


def run_agent_from_chat(name, source_registry, store, write=print, chat_loop_fn=None):
    """Start the named agent's chat loop, or print the menu for an empty name.

    The registry and store come from the caller, so the agent shares your
    safety policy and saved-conversation storage. `chat_loop_fn` is for tests.
    """
    if not name:
        write(agent_menu())
        return False
    try:
        spec = get_agent(name)
    except AgentError as e:
        write(f"{e}\n")
        return False

    from agents.factory import new_agent_chat
    from agents.history import load_messages, save_messages, to_contents
    from app.llm import client, MODEL

    if chat_loop_fn is None:
        from agents.runner import chat_loop as chat_loop_fn

    messages = load_messages(store, spec)
    chat, registry = new_agent_chat(
        client, MODEL, spec, source_registry, to_contents(messages)
    )
    chat_loop_fn(
        chat,
        registry,
        spec,
        messages=messages,
        save=lambda m: save_messages(store, spec, m),
    )
    write("(Back in the main chat.)\n")
    return True