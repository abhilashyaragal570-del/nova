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
    print("Nova is ready. Type 'exit' to quit.\n")
    while True:
        user_input = input("You: ").strip()
        if user_input.lower() in ("exit", "quit"):
            print("Nova: Goodbye!")
            break
        if not user_input:
            continue
        reply = chat.send_message(user_input)
        print(f"Nova: {reply.text}\n")


if __name__ == "__main__":
    main()
