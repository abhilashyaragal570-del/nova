"""Usage: python -m agents <name> [--clear]
       python -m agents --auto
       python -m agents nova --clear
       python -m agents --route <question>"""
import sys

from agents.definitions import AgentError, get_agent, list_agents


def _run_auto() -> int:
    # Imported here so the usage message works without touching the API setup.
    from agents.auto import DEFAULT_AGENT, Session, auto_loop, nova_spec
    from agents.factory import new_agent_chat
    from agents.history import load_messages, save_messages, to_contents
    from app.chat import SYSTEM_PROMPT, registry, store
    from app.llm import client, MODEL

    def make_session(name):
        if name == DEFAULT_AGENT:
            spec = nova_spec(registry, SYSTEM_PROMPT)
        else:
            spec = get_agent(name)
        messages = load_messages(store, spec)
        chat, agent_registry = new_agent_chat(
            client, MODEL, spec, registry, to_contents(messages)
        )
        return Session(spec, chat, agent_registry, messages)

    auto_loop(
        make_session,
        save=lambda s: save_messages(store, s.spec, s.messages),
    )
    return 0


def main(argv) -> int:
    if len(argv) >= 3 and argv[1] == "--route":
        from agents.router import route

        name = route(" ".join(argv[2:]))
        print(name or "no agent matches (use the normal Nova chat)")
        return 0

    if len(argv) == 2 and argv[1] == "--auto":
        return _run_auto()

    if len(argv) == 3 and argv[1].lower() == "nova" and argv[2] == "--clear":
        from agents.history import conversation_id
        from app.chat import store

        store.delete(conversation_id("nova"))
        print("Cleared the saved nova conversation.")
        return 0

    clear = len(argv) == 3 and argv[2] == "--clear"
    if len(argv) != 2 and not clear:
        print("Usage: python -m agents <name> [--clear]\n\nAvailable agents:")
        for spec in list_agents():
            print(f"  {spec.name:<12} {spec.description}")
        print("\n--auto picks an agent for each question (general chat if none fits).")
        print("--clear deletes that agent's saved conversation.")
        print("nova --clear deletes the general chat used by --auto.")
        print("--route <question> shows which agent would handle a question.")
        return 1
    try:
        spec = get_agent(argv[1])
    except AgentError as e:
        print(e)
        return 1

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