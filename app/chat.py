from google.genai import errors, types
from app.confirm import confirm_in_terminal
from app.llm import client, MODEL
from app.tool_loop import run_turn
from config import settings
from memory.conversation_store import MAIN_ID, ConversationStore
from tools.calculator import CalculatorTool
from tools.file_tools import ListFilesTool, ReadFileTool, WriteFileTool
from tools.gemini_adapter import to_gemini_tool
from tools.policy import ToolPolicy
from tools.registry import ToolRegistry
from tools.web_search import WebSearchTool
from tools.api_request import ApiRequestTool

SYSTEM_PROMPT = settings.NOVA_SYSTEM_PROMPT
store = ConversationStore()

# Every tool call passes through this registry. The policy asks you to
# approve any tool that is not read-only (currently: write_file, api_request).
registry = ToolRegistry(policy=ToolPolicy(confirm=confirm_in_terminal))
registry.register(CalculatorTool())
registry.register(WebSearchTool())
registry.register(ListFilesTool())
registry.register(ReadFileTool())
registry.register(WriteFileTool())
registry.register(ApiRequestTool())


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


def new_chat(messages, system_prompt=SYSTEM_PROMPT):
    gemini_tool = to_gemini_tool(registry)
    return client.chats.create(
        model=MODEL,
        config=types.GenerateContentConfig(
            system_instruction=system_prompt,
            tools=[gemini_tool] if gemini_tool else None,
        ),
        history=to_contents(messages),
    )


def main():
    messages = store.load(MAIN_ID)["messages"]
    system_prompt = SYSTEM_PROMPT
    chat = new_chat(messages, system_prompt)
    total_tokens = 0
    print("Nova is ready. Commands: exit, /clear, /history, /model, /system")
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
        if user_input.lower() == "/system":
            print("Nova: Current personality: " + system_prompt + "\n")
            continue
        if user_input.lower().startswith("/system "):
            system_prompt = user_input[len("/system "):].strip()
            chat = new_chat(messages, system_prompt)
            print("Nova: Personality updated for this session.\n")
            continue
        if user_input.lower() == "/model":
            print("Nova: Using model " + MODEL + "\n")
            continue
        if user_input.lower() == "/history":
            show_history(messages)
            continue
        if user_input.lower() == "/clear":
            messages = []
            chat = new_chat(messages, system_prompt)
            store.delete(MAIN_ID)
            print("Nova: Memory cleared. Starting fresh.\n")
            continue
        print("Nova: ", end="", flush=True)
        try:
            result = run_turn(
                chat,
                user_input,
                registry,
                on_text=lambda t: print(t, end="", flush=True),
            )
        except errors.APIError as e:
            print(f"\n[Nova couldn't reply: error {e.code}. Try again in a moment.]\n")
            continue
        print()
        if result.tool_calls:
            print(f"[used {result.tool_calls} tool call(s)]")
        if result.hit_round_limit:
            print("[tool call limit reached]")
        if result.reply:
            messages.append({"role": "user", "text": user_input})
            messages.append({"role": "model", "text": result.reply})
            store.save(MAIN_ID, "Main chat", messages)
        if result.total_tokens:
            total_tokens += result.total_tokens
            print(
                f"[tokens: prompt {result.prompt_tokens}, "
                f"reply {result.reply_tokens}, "
                f"total {result.total_tokens}]\n"
            )


if __name__ == "__main__":
    main()