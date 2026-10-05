from google.genai import types
from app.llm import client, MODEL

SYSTEM_PROMPT = (
    "You are Nova, a friendly and precise AI assistant. "
    "Keep answers clear and concise."
)


def main():
    chat = client.chats.create(
        model=MODEL,
        config=types.GenerateContentConfig(system_instruction=SYSTEM_PROMPT),
    )
    total_tokens = 0
    print("Nova is ready. Type 'exit' to quit.\n")
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
        if usage:
            total_tokens += usage.total_token_count or 0
            print(
                f"[tokens: prompt {usage.prompt_token_count}, "
                f"reply {usage.candidates_token_count}, "
                f"total {usage.total_token_count}]\n"
            )


if __name__ == "__main__":
    main()
