"""Terminal chat loop for a specialized agent.

The chat, registry and I/O functions are passed in, so tests can drive the loop
with fakes and never touch the real API.
"""
from google.genai import errors

from agents.definitions import AgentSpec
from app.tool_loop import run_turn


def _echo(text: str) -> None:
    print(text, end="", flush=True)


def chat_loop(chat, registry, spec: AgentSpec, read=input, write=_echo) -> int:
    """Run the loop until the user exits. Returns the session's token total."""
    total_tokens = 0
    name = spec.name
    write(f"{name} agent is ready: {spec.description}\n")
    write("Type exit to leave.\n\n")
    while True:
        try:
            user_input = read("You: ").strip()
        except (KeyboardInterrupt, EOFError):
            write(f"\n{name}: Goodbye! (session total: {total_tokens} tokens)\n")
            break
        if user_input.lower() in ("exit", "quit"):
            write(f"{name}: Goodbye! (session total: {total_tokens} tokens)\n")
            break
        if not user_input:
            continue
        write(f"{name}: ")
        try:
            result = run_turn(chat, user_input, registry, on_text=write)
        except errors.APIError as e:
            write(f"\n[{name} couldn't reply: error {e.code}. Try again in a moment.]\n\n")
            continue
        write("\n")
        if result.tool_calls:
            write(f"[used {result.tool_calls} tool call(s)]\n")
        if result.hit_round_limit:
            write("[tool call limit reached]\n")
        if result.total_tokens:
            total_tokens += result.total_tokens
            write(
                f"[tokens: prompt {result.prompt_tokens}, "
                f"reply {result.reply_tokens}, "
                f"total {result.total_tokens}]\n\n"
            )
    return total_tokens