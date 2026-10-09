"""Auto-routing chat: each question goes to the agent the router picks.

Questions no rule matches go to a general "nova" chat that has every tool,
unless they are short follow-ups to a specialized agent's last answer. The
session factory, save callback and I/O functions are passed in, so tests can
drive the loop with fakes and never touch the real API or the disk.
"""
from dataclasses import dataclass
from typing import Any

from google.genai import errors

from agents.definitions import AGENTS, AgentSpec
from agents.router import route
from app.tool_loop import run_turn

DEFAULT_AGENT = "nova"
FOLLOWUP_MAX_WORDS = 4


@dataclass
class Session:
    spec: AgentSpec
    chat: Any
    registry: Any
    messages: list


def nova_spec(source, system_prompt: str) -> AgentSpec:
    """The general chat: every tool in `source`, the main system prompt."""
    return AgentSpec(
        name=DEFAULT_AGENT,
        description="General chat with all tools (asks before writing or calling APIs).",
        system_prompt=system_prompt,
        tools=frozenset(tool.name for tool in source.all()),
    )


def choose_agent(text: str, pinned, last_agent) -> str:
    """Pick the agent for this message.

    Order: pinned agent, a clear router match, a short follow-up to the last
    specialized agent, then the general chat.
    """
    if pinned:
        return pinned
    routed = route(text)
    if routed:
        return routed
    if last_agent in AGENTS and len(text.split()) <= FOLLOWUP_MAX_WORDS:
        return last_agent
    return DEFAULT_AGENT


def _echo(text: str) -> None:
    print(text, end="", flush=True)


def auto_loop(make_session, save=None, read=input, write=_echo) -> int:
    """Run until the user exits. Returns the session's token total.

    `make_session(name)` returns a Session. `save(session)` is called after
    each answered turn, if given.
    """
    valid = set(AGENTS) | {DEFAULT_AGENT}
    names = ", ".join(sorted(valid))
    sessions = {}
    pinned = None
    last_agent = None
    total_tokens = 0
    write("Auto mode: each question goes to the agent the router picks.\n")
    write(f"Agents: {names}\n")
    write("Commands: /use <agent> to pin one, /auto to route again, exit.\n\n")
    while True:
        try:
            user_input = read("You: ").strip()
        except (KeyboardInterrupt, EOFError):
            write(f"\nGoodbye! (session total: {total_tokens} tokens)\n")
            break
        lowered = user_input.lower()
        if lowered in ("exit", "quit"):
            write(f"Goodbye! (session total: {total_tokens} tokens)\n")
            break
        if not user_input:
            continue
        if lowered == "/auto":
            pinned = None
            write("Routing is automatic again.\n\n")
            continue
        if lowered == "/use" or lowered.startswith("/use "):
            wanted = lowered[4:].strip()
            if wanted not in valid:
                write(f"Unknown agent. Choose from: {names}\n\n")
                continue
            pinned = wanted
            write(f"Pinned to {wanted}. Type /auto to route again.\n\n")
            continue

        name = choose_agent(user_input, pinned, last_agent)
        if name not in sessions:
            try:
                sessions[name] = make_session(name)
            except Exception as e:  # a bad saved file must not end the session
                write(f"[couldn't start {name}: {e}]\n\n")
                continue
        session = sessions[name]

        write(f"[{name}] ")
        try:
            result = run_turn(
                session.chat, user_input, session.registry, on_text=write
            )
        except errors.APIError as e:
            write(f"\n[{name} couldn't reply: error {e.code}. Try again in a moment.]\n\n")
            continue
        write("\n")
        if result.tool_calls:
            write(f"[used {result.tool_calls} tool call(s)]\n")
        if result.hit_round_limit:
            write("[tool call limit reached]\n")
        if result.reply:
            last_agent = name
            session.messages.append({"role": "user", "text": user_input})
            session.messages.append({"role": "model", "text": result.reply})
            if save is not None:
                try:
                    save(session)
                except Exception as e:
                    write(f"[couldn't save this chat: {e}]\n")
        if result.total_tokens:
            total_tokens += result.total_tokens
            write(
                f"[tokens: prompt {result.prompt_tokens}, "
                f"reply {result.reply_tokens}, "
                f"total {result.total_tokens}]\n\n"
            )
    return total_tokens