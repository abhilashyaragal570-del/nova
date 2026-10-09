"""Terminal chat loop for a specialized agent.

The chat, registry, I/O functions and save callback are passed in, so tests can
drive the loop with fakes and never touch the real API or the disk.
"""
from google.genai import errors

from agents.definitions import AgentSpec
from app.tool_loop import run_turn


def _echo(text: str) -> None:
    print(text, end="", flush=True)


def chat_loop(
    chat,
    registry,
    spec: AgentSpec,
    read=input,
    write=_echo,
    messages=None,
    save=None,
) -> int:
    """Run the loop until the user exits. Returns the session's token total.

    `messages` is the saved history (a list that this function appends to).
    `save(messages)` is called after each answered turn, if given.
    """
    messages = [] if messages is None else messages
    total_tokens = 0
    name = spec.name
    write(f"{name} agent is ready: {spec.description}\n")
    write("Type exit to leave.\n")
    if messages:
        write(f"(Loaded {len(messages)} earlier messages.)\n")
    write("\n")
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
        if result.reply:
            messages.append({"role": "user", "text": user_input})
            messages.append({"role": "model", "text": result.reply})
            if save is not None:
                try:
                    save(messages)
                except Exception as e:  # a storage problem must not end the session
                    write(f"[couldn't save this chat: {e}]\n")
        if result.total_tokens:
            total_tokens += result.total_tokens
            write(
                f"[tokens: prompt {result.prompt_tokens}, "
                f"reply {result.reply_tokens}, "
                f"total {result.total_tokens}]\n\n"
            )
    return total_tokens