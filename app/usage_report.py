"""Reads the tool usage log and prints a short summary.

Deliberately does not import config.settings, so it works without a
GEMINI_API_KEY. Lines that cannot be read are counted and skipped.

When the log is rotated (see app/usage_log.py), the full file is kept as
<name>.1. The report reads that older file first and then the current one, so
the totals do not drop back to zero after a rotation. Only one older file
exists, so the report covers at most the last two files.

Turns that were timed also have a duration_seconds value, and some have an
approval_wait_seconds value: the time spent waiting for the person to click
Approve or Deny. The latency numbers (average, median, 95th percentile and
slowest) use the duration minus that wait, so they show how long Nova itself
took. Older lines and turns that were not timed (such as the terminal chat) are
left out of the latency numbers but still counted everywhere else.

Workflow runs are logged with source "workflow" (see app/workflow_log.py).
They have their own total, workflow_seconds, so they never mix into the chat
latency numbers. The Workflows section counts runs by final status and shows
run times the same way as chat: the approval wait is left out.

Usage: python -m app.usage_report
"""
import json
import math
import sys
from collections import Counter
from pathlib import Path
from statistics import median

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


def old_log_path(path: Path) -> Path:
    """Where usage_log.py moves a full log: <name>.1 next to the current file."""
    path = Path(path)
    return path.with_name(path.name + ".1")


def read_all_entries(path: Path) -> tuple[list, int]:
    """Read the older rotated file first, then the current one.

    Returns (entries, skipped_line_count) over both files. A file that does
    not exist counts as empty.
    """
    old_entries, old_skipped = read_entries(old_log_path(path))
    entries, skipped = read_entries(path)
    return old_entries + entries, old_skipped + skipped


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


def _seconds(value) -> float | None:
    """A usable number of seconds, or None for anything else."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    if not math.isfinite(value) or value < 0:
        return None
    return float(value)


def _count(value) -> int:
    """A usable whole number for a counter field, or 0 for anything else."""
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        return 0
    return value


def _timed_turns(entries: list) -> list:
    """(active_seconds, approval_wait_seconds) for each usable timed turn.

    active_seconds is the duration minus the approval wait, never below zero.
    A missing or unusable wait counts as zero.
    """
    turns = []
    for entry in entries:
        duration = _seconds(entry.get("duration_seconds"))
        if duration is None:
            continue
        wait = _seconds(entry.get("approval_wait_seconds")) or 0.0
        turns.append((max(0.0, duration - wait), wait))
    return turns


def percentile(values: list, pct: float) -> float | None:
    """The nearest-rank percentile of values, or None when there are none."""
    ordered = sorted(values)
    if not ordered:
        return None
    rank = max(1, math.ceil(pct * len(ordered) / 100))
    return ordered[min(rank, len(ordered)) - 1]


def summarize_latency(entries: list) -> dict | None:
    """Turn-time numbers over the timed turns, or None when none were timed.

    The times leave out the approval wait. approval_wait_seconds is the total
    that was left out, and turns_with_approval counts the turns that had any.
    """
    turns = _timed_turns(entries)
    if not turns:
        return None
    active = [a for a, _ in turns]
    waits = [w for _, w in turns]
    return {
        "turns": len(turns),
        "average_seconds": round(sum(active) / len(active), 3),
        "median_seconds": round(median(active), 3),
        "p95_seconds": round(percentile(active, 95), 3),
        "max_seconds": round(max(active), 3),
        "approval_wait_seconds": round(sum(waits), 3),
        "turns_with_approval": sum(1 for w in waits if w > 0),
    }


def summarize_workflows(entries: list) -> dict | None:
    """Numbers over the workflow runs, or None when there are none.

    A workflow run is a log line with source "workflow". The times come from
    workflow_seconds minus the approval wait, never below zero. Runs without a
    usable workflow_seconds still count in runs, statuses, tasks and tool
    calls, but are left out of the time numbers (timed_runs says how many
    were used). The time fields are None when no run was timed.
    """
    runs = [e for e in entries if e.get("source") == "workflow"]
    if not runs:
        return None
    statuses: Counter = Counter()
    tools: Counter = Counter()
    tasks = 0
    tool_calls = 0
    active = []
    waits = []
    for run in runs:
        status = run.get("status")
        statuses[status if isinstance(status, str) and status else "unknown"] += 1
        tools.update(t for t in (run.get("tools") or []) if isinstance(t, str))
        tasks += _count(run.get("tasks"))
        tool_calls += _count(run.get("tool_calls"))
        duration = _seconds(run.get("workflow_seconds"))
        if duration is None:
            continue
        wait = _seconds(run.get("approval_wait_seconds")) or 0.0
        active.append(max(0.0, duration - wait))
        waits.append(wait)
    result = {
        "runs": len(runs),
        "statuses": dict(statuses),
        "tasks": tasks,
        "tool_calls": tool_calls,
        "tools": dict(tools),
        "timed_runs": len(active),
        "average_seconds": None,
        "median_seconds": None,
        "max_seconds": None,
        "approval_wait_seconds": 0.0,
        "runs_with_approval": 0,
    }
    if active:
        result["average_seconds"] = round(sum(active) / len(active), 3)
        result["median_seconds"] = round(median(active), 3)
        result["max_seconds"] = round(max(active), 3)
        result["approval_wait_seconds"] = round(sum(waits), 3)
        result["runs_with_approval"] = sum(1 for w in waits if w > 0)
    return result


def format_latency(latency: dict) -> str:
    lines = [
        f"Latency ({latency['turns']} timed turns):",
        f"  average  {latency['average_seconds']:.2f}s",
        f"  median   {latency['median_seconds']:.2f}s",
        f"  95th     {latency['p95_seconds']:.2f}s",
        f"  slowest  {latency['max_seconds']:.2f}s",
    ]
    count = latency.get("turns_with_approval", 0)
    if count:
        lines.append(
            f"  (left out: {latency.get('approval_wait_seconds', 0):.2f}s "
            f"spent waiting for approval in {count} turns)"
        )
    return "\n".join(lines)


def format_workflows(workflows: dict) -> str:
    lines = [
        f"Workflows ({workflows['runs']} runs):",
        f"  tasks        {workflows['tasks']}",
        f"  tool calls   {workflows['tool_calls']}",
    ]
    statuses = sorted(workflows["statuses"].items(), key=lambda kv: (-kv[1], kv[0]))
    if statuses:
        width = max(len(name) for name, _ in statuses)
        lines.append("  by status:")
        for name, count in statuses:
            lines.append(f"    {name:<{width}}  {count}")
    if workflows["timed_runs"]:
        lines.extend(
            [
                f"  average  {workflows['average_seconds']:.2f}s",
                f"  median   {workflows['median_seconds']:.2f}s",
                f"  slowest  {workflows['max_seconds']:.2f}s",
            ]
        )
        count = workflows.get("runs_with_approval", 0)
        if count:
            lines.append(
                f"  (left out: {workflows.get('approval_wait_seconds', 0):.2f}s "
                f"spent waiting for approval in {count} runs)"
            )
    else:
        lines.append("  (no timed runs)")
    return "\n".join(lines)


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
    old = old_log_path(path)
    if not path.exists() and not old.exists():
        print(f"No usage log found at {path}. Chat with Nova first, then run this again.")
        return 1
    entries, skipped = read_all_entries(path)
    print(f"Tool usage report ({path})\n")
    if old.exists():
        print(f"(includes the older log {old.name})\n")
    print(format_report(summarize(entries), skipped))
    latency = summarize_latency(entries)
    if latency:
        print("")
        print(format_latency(latency))
    workflows = summarize_workflows(entries)
    if workflows:
        print("")
        print(format_workflows(workflows))
    return 0


if __name__ == "__main__":
    sys.exit(main())