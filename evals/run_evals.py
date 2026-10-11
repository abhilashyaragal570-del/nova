"""Runs each question in evals/questions.json through Nova and checks which
tools it used.

A question passes when every expected tool was used. Extra read-only calls
are allowed, except that a question expecting no tools must use none. Only
read-only tools are registered, so nothing ever asks for approval. Results are
printed and saved to evals/last_results.json.

Usage: python -m evals.run_evals
"""
import json
import sys
from pathlib import Path

from google.genai import errors, types

from app.llm import MODEL, client
from app.tool_loop import run_turn
from config import settings
from tools.calculator import CalculatorTool
from tools.file_tools import ListFilesTool, ReadFileTool
from tools.gemini_adapter import to_gemini_tool
from tools.registry import ToolRegistry
from tools.web_search import WebSearchTool

EVALS_DIR = Path(__file__).resolve().parent
QUESTIONS_FILE = EVALS_DIR / "questions.json"
RESULTS_FILE = EVALS_DIR / "last_results.json"


def build_registry() -> ToolRegistry:
    registry = ToolRegistry()
    registry.register(CalculatorTool())
    registry.register(WebSearchTool())
    registry.register(ListFilesTool())
    registry.register(ReadFileTool())
    return registry


def load_questions(path: Path = QUESTIONS_FILE) -> list:
    return json.loads(path.read_text(encoding="utf-8"))


def judge(expected: list, used: list) -> bool:
    """Pass when every expected tool was used.

    Extra tool calls are allowed (for example list_files before read_file).
    A question that expects no tools passes only if none were used.
    """
    if not expected:
        return not used
    return set(expected) <= set(used)


def run_question(item: dict, registry: ToolRegistry) -> dict:
    gemini_tool = to_gemini_tool(registry)
    chat = client.chats.create(
        model=MODEL,
        config=types.GenerateContentConfig(
            system_instruction=settings.NOVA_SYSTEM_PROMPT,
            tools=[gemini_tool] if gemini_tool else None,
        ),
    )
    entry = {
        "id": item["id"],
        "question": item["question"],
        "expected": item["expected_tools"],
    }
    try:
        result = run_turn(chat, item["question"], registry)
    except errors.APIError as e:
        entry.update(used=[], passed=False, error=f"API error {e.code}", tokens=0)
        return entry
    entry.update(
        used=result.tools_used,
        passed=judge(item["expected_tools"], result.tools_used),
        tokens=result.total_tokens,
    )
    return entry


def main() -> int:
    questions = load_questions()
    registry = build_registry()
    results = []
    for item in questions:
        outcome = run_question(item, registry)
        results.append(outcome)
        mark = "PASS" if outcome["passed"] else "FAIL"
        print(
            f"{mark}  {outcome['id']:<8} expected={outcome['expected']} "
            f"used={outcome['used']}"
        )
        if outcome.get("error"):
            print(f"      {outcome['error']}")
    passed = sum(1 for r in results if r["passed"])
    print(f"\n{passed}/{len(results)} passed")
    RESULTS_FILE.write_text(json.dumps(results, indent=2), encoding="utf-8")
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())