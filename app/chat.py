import json
from pathlib import Path

from google.genai import errors, types
from app.confirm import confirm_in_terminal
from app.llm import client, MODEL
from app.tool_loop import run_turn
from config import settings
from tools.calculator import CalculatorTool
from tools.file_tools import ListFilesTool, ReadFileTool, WriteFileTool
from tools.gemini_adapter import to_gemini_tool
from tools.policy import ToolPolicy
from tools.registry import ToolRegistry
from tools.web_search import WebSearchTool
from tools.api_request import ApiRequestTool

SYSTEM_PROMPT = settings.NOVA_SYSTEM_PROMPT
HISTORY_FILE = Path("history.json")

# Every tool call passes through this registry. The policy asks you to
# approve any tool that is not read-only (currently: write_file, api_request).
registry = ToolRegistry(policy=ToolPolicy(confirm=confirm_in_terminal))
registry.register(CalculatorTool())
registry.register(WebSearchTool())
registry.register(ListFilesTool())
registry.register(ReadFileTool())
registry.register(WriteFileTool())
registry.register(ApiRequestTool())


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
    messages