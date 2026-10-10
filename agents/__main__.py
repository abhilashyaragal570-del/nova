"""Run Nova's specialized agents from the terminal. See USAGE below."""
import sys

from agents.definitions import AgentError, get_agent, list_agents

USAGE = """Usage:
  python -m agents <name>             chat with one agent (resumes its saved chat)
  python -m agents <name> --clear     delete that agent's saved conversation
  python -m agents --auto             pick an agent for each question
  python -m agents --auto --smart     same, and ask the model when no rule matches
  python -m agents nova --clear       delete the general chat used by --auto
  python -m agents --route <text>     show which agent would handle <text>

In --auto mode: /use <agent> pins an agent, /auto goes back to routing.
"""


def print_usage() -> None:
    print(USAGE)
    print("Available agents:")
    for spec in list_agents():
        print(f"  {spec.name:<12} {spec.description}")


def _run_auto(smart: bool) -> int:
    # Imported here so the usage message works without touching the API setup.
    from agents.auto import DEFAULT_AGENT, Session, auto_loop, nova_spec
    from agents.factory import new_agent_chat
    from agents.history import load_messages, save_messages, to_contents
    from agents.smart_router import make_classifier
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
        classify=make_classifier(client, MODEL) if smart else None,
    )
    return 0


def _run_agent(spec, clear: bool) -> int:
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


def main(argv) -> int:
    if len(argv) >= 3 and argv[1] == "--route":
        from agents.router import route

        name = route(" ".join(argv[2:]))
        print(name or "no agent matches (use the normal Nova chat)")
        return 0

    if argv[1:2] == ["--auto"] and (len(argv) == 2 or argv[2:] == ["--smart"]):
        return _run_auto(smart=len(argv) == 3)

    if len(argv) == 3 and argv[1].lower() == "nova" and argv[2] == "--clear":
        from agents.history import conversation_id
        from app.chat import store

        store.delete(conversation_id("nova"))
        print("Cleared the saved nova conversation.")
        return 0

    clear = len(argv) == 3 and argv[2] == "--clear"
    if len(argv) != 2 and not clear:
        print_usage()
        return 1
    try:
        spec = get_agent(argv[1])
    except AgentError as e:
        print(e)
        return 1
    return _run_agent(spec, clear)


if __name__ == "__main__":
    sys.exit(main(sys.argv))