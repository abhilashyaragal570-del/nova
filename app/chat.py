import json
from pathlib import Path

from google.genai import types
from app.llm import client, MODEL

SYSTEM_PROMPT = (
    "You are Nova, a friendly and precise AI assistant. "
    "Keep answers clear and concise."
)
HISTORY_FILE = Path("history.json")


def load_history():
    if not HISTORY_FILE.exists():
        return []
    try:
        data = json.loads(HISTORY_FILE.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return []
    return [
        types.Content(role=m["role"], parts=[types.Part(text=m["text"])])
        for m in data
    ]


def save_history(chat):
    data = []
    for content in chat.get_history():
        text = "".join(p.text or "" for p in (content.parts or []))
        data.append({"role": content.role, "text": text})
    HISTORY_FILE.write_text(
        json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8"
    )


def main():
    history = load_history()
    chat = client.chats.create(
        model=MODEL,
        config=types.GenerateContentConfig(system_instruction=SYSTEM_PROMPT),
        history=history,
    )
    total_tokens = 0
    print("Nova is ready. Type 'exit' to quit.")
    if history:
        print(f"(Loaded {len(history)} earlier messages.)")
    print()
    while True:
        user_input = input("You: ").strip()
        if user_input.lower() in ("exit", "quit"):
            print(f"Nova: Goodbye! (session total: {total_tokens} tokens)")
            break
        if not user_input:
            continue
        print("Nova: ", end="", flush=True)
        usage = None
        for chunk in chat.send_message_stream(user_input):
            if chunk.text:
                print(chunk.text, end="", flush=True)
            if chunk.usage_metadata:
                usage = chunk.usage_metadata
        print()
        save_history(chat)
        if usage:
            total_tokens += usage.total_token_count or 0
            print(
                f"[tokens: prompt {usage.prompt_token_count}, "
                f"reply {usage.candidates_token_count}, "
                f"total {usage.total_token_count}]\n"
            )


if __name__ == "__main__":
    main()
