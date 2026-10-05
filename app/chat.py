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
        print("Nova: ", end="", flush=True)
        for chunk in chat.send_message_stream(user_input):
            if chunk.text:
                print(chunk.text, end="", flush=True)
        print("\n")


if __name__ == "__main__":
    main()
