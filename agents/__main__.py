"""Usage: python -m agents <name> [--clear]
       python -m agents --route <question>"""
import sys

from agents.definitions import AgentError, get_agent, list_agents


def main(argv) -> int:
    if len(argv) >= 3 and argv[1] == "--route":
        from agents.router import route

        name = route(" ".join(argv[2:]))
        print(name or "no agent matches (use the normal Nova chat)")
        return 0

    clear = len(argv) == 3 and argv[2] == "--clear"
    if len(argv) != 2 and not clear:
        print("Usage: python -m agents <name> [--clear]\n\nAvailable agents:")
        for spec in list_agents():
            print(f"  {spec.name:<12} {spec.description}")
        print("\n--clear deletes that agent's saved conversation.")
        print("--route <question> shows which agent would handle a question.")
        return 1
    try:
        spec = get_agent(argv[1])
    except AgentError as e:
        print(e)
        return 1

    # Imported here so the usage message works without touching the API setup.
    from agents.factory import new_agent_chat
    from agents.history import (
        clear_messages,
        load_messages,
        save_messages,
        to_contents,
    )
    from agents.runner import chat_loop
    from app.chat import registry, store
    from app.llm import client, MODEL

    if clear:
        clear_messages(store, spec)
        print(f"Cleared the saved {spec.name} conversation.")
        return 0

    messages = load_messages(store, spec)
    chat, agent_registry = new_agent_chat(
        client, MODEL, spec, registry, to_contents(messages)
    )
    chat_loop(
        chat,
        agent_registry,
        spec,
        messages=messages,
        save=lambda m: save_messages(store, spec, m),
    )
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))