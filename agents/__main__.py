"""Usage: python -m agents <name>"""
import sys

from agents.definitions import AgentError, get_agent, list_agents


def main(argv) -> int:
    if len(argv) != 2:
        print("Usage: python -m agents <name>\n\nAvailable agents:")
        for spec in list_agents():
            print(f"  {spec.name:<12} {spec.description}")
        return 1
    try:
        spec = get_agent(argv[1])
    except AgentError as e:
        print(e)
        return 1

    # Imported here so the usage message works without touching the API setup.
    from agents.factory import new_agent_chat
    from agents.runner import chat_loop
    from app.chat import registry
    from app.llm import client, MODEL

    chat, agent_registry = new_agent_chat(client, MODEL, spec, registry)
    chat_loop(chat, agent_registry, spec)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))