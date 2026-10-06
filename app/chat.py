import json
from pathlib import Path

from google.genai import errors, types
from app.llm import client, MODEL
from config import settings

SYSTEM_PROMPT = settings.NOVA_SYSTEM_PROMPT
HISTORY_FILE = Path("history.json")


def load_history():
    if not HISTORY_FILE.exists():
        return []
    try:
        data = json.loads(HISTORY_FILE.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return []
    return [m for m in data if m.get("text")]


def save_history(messages):
    HISTORY_FILE.write_text(
        json.dumps(messages, indent=2, ensure_ascii=False), encoding="utf-8"
    )


def to_contents(messages):
    return [
        types.Content(role=m["role"], parts=[types.Part(text=m["text"])])
        for m in messages
    ]


def show_history(messages, count=6):
    if not messages:
        print("Nova: No history yet.\n")
        return
    for m in messages[-count:]:
        who = "You" if m["role"] == "user" else "Nova"
        print(f"{who}: {m['text'][:200]}")
    print()


def new_chat(messages):
    return client.chats.create(
        model=MODEL,
        config=types.GenerateContentConfig(system_instruction=SYSTEM_PROMPT),
        history=to_contents(messages),
    )


def main():
    messages = load_history()
    chat = new_chat(messages)
    total_tokens = 0
    print("Nova is ready. Commands: exit, /clear, /history, /model")
    if messages:
        print(f"(Loaded {len(messages)} earlier messages.)")
    print()
    while True:
        try:
            user_input = input("You: ").strip()
        except (KeyboardInterrupt, EOFError):
            print(f"\nNova: Goodbye! (session total: {total_tokens} tokens)")
            break
        if user_input.lower() in ("exit", "quit"):
            print(f"Nova: Goodbye! (session total: {total_tokens} tokens)")
            break
        if not user_input:
            continue
        if user_input.lower() == "/model":
            print("Nova: Using model " + MODEL + "\n")
            continue
        if user_input.lower() == "/history":
            show_history(messages)
            continue
        if user_input.lower() == "/clear":
            messages = []
            chat = new_chat(messages)
            HISTORY_FILE.unlink(missing_ok=True)
            print("Nova: Memory cleared. Starting fresh.\n")
            continue
        print("Nova: ", end="", flush=True)
        usage = None
        reply = ""
        try:
            for chunk in chat.send_message_stream(user_input):
                if chunk.text:
                    reply += chunk.text
                    print(chunk.text, end="", flush=True)
                if chunk.usage_metadata:
                    usage = chunk.usage_metadata
        except errors.APIError as e:
            print(f"\n[Nova couldn't reply: error {e.code}. Try again in a moment.]\n")
            continue
        print()
        if reply:
            messages.append({"role": "user", "text": user_input})
            messages.append({"role": "model", "text": reply})
            save_history(messages)
        if usage:
            total_tokens += usage.total_token_count or 0
            print(
                f"[tokens: prompt {usage.prompt_token_count}, "
                f"reply {usage.candidates_token_count}, "
                f"total {usage.total_token_count}]\n"
            )


if __name__ == "__main__":
    main()