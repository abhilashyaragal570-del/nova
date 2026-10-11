"""Reads the tool usage log and prints a short summary.

Deliberately does not import config.settings, so it works without a
GEMINI_API_KEY. Lines that cannot be read are counted and skipped.

Usage: python -m app.usage_report
"""
import json
import sys
from collections import Counter
from pathlib import Path

from app.usage_log import get_log_path


def read_entries(path: Path) -> tuple[list, int]:
    """Return (entries, skipped_line_count). A missing file gives ([], 0)."""
    try:
        lines = Path(path).read_text(encoding="utf-8").splitlines()
    except OSError:
        return [], 0
    entries = []
    skipped = 0
    for line in lines:
        if not line.strip():
            continue
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            skipped += 1
            continue
        if isinstance(entry, dict):
            entries.append(entry)
        else:
            skipped += 1
    return entries, skipped


def summarize(entries: list) -> dict:
    """Count tools, tokens and turns, overall and per source."""
    tools: Counter = Counter()
    sources: dict = {}
    total_tokens = 0
    no_tool_turns = 0
    limit_hits = 0
    for entry in entries:
        used = entry.get("tools") or []
        tools.update(used)
        if not used:
            no_tool_turns += 1
        if entry.get("hit_round_limit"):
            limit_hits += 1
        tokens = entry.get("total_tokens") or 0
        total_tokens += tokens
        bucket = sources.setdefault(entry.get("source", "unknown"), {"turns": 0, "tokens": 0})
        bucket["turns"] += 1
        bucket["tokens"] += tokens
    return {
        "turns": len(entries),
        "total_tokens": total_tokens,
        "no_tool_turns": no_tool_turns,
        "limit_hits": limit_hits,
        "tools": dict(tools),
        "sources": sources,
    }


def format_report(summary: dict, skipped: int = 0) -> str:
    lines = [
        f"Turns: {summary['turns']}",
        f"Total tokens: {summary['total_tokens']:,}",
        f"Turns with no tools: {summary['no_tool_turns']}",
        f"Turns that hit the round limit: {summary['limit_hits']}",
    ]
    if skipped:
        lines.append(f"Unreadable log lines skipped: {skipped}")

    lines.append("")
    lines.append("Tools used:")
    tools = sorted(summary["tools"].items(), key=lambda kv: (-kv[1], kv[0]))
    if tools:
        width = max(len(name) for name, _ in tools)
        for name, count in tools:
            lines.append(f"  {name:<{width}}  {count}")
    else:
        lines.append("  (none)")

    lines.append("")
    lines.append("By source:")
    sources = sorted(
        summary["sources"].items(), key=lambda kv: (-kv[1]["tokens"], kv[0])
    )
    if sources:
        width = max(len(name) for name, _ in sources)
        for name, info in sources:
            lines.append(
                f"  {name:<{width}}  {info['turns']} turns  {info['tokens']:,} tokens"
            )
    else:
        lines.append("  (none)")
    return "\n".join(lines)


def main() -> int:
    path = get_log_path()
    if not path.exists():
        print(f"No usage log found at {path}. Chat with Nova first, then run this again.")
        return 1
    entries, skipped = read_entries(path)
    print(f"Tool usage report ({path})\n")
    print(format_report(summarize(entries), skipped))
    return 0


if __name__ == "__main__":
    sys.exit(main())