"""Pick a specialized agent for a question using simple, predictable rules.

No model calls: the same question always gives the same answer. Rules are
checked in priority order and the first match wins. None means "no agent fits,
use the normal chat".
"""
import re

_URL = re.compile(r"https?://\S+")

_NOTES = (
    re.compile(r"\bmy\s+(?:notes|documents|docs)\b", re.I),
    re.compile(r"\b(?:uploaded|added|indexed)\s+(?:documents|docs|notes)\b", re.I),
)

_FILES = (
    re.compile(
        r"\b(?:list|show|read|open|view|display)\s+(?:me\s+)?"
        r"(?:the\s+|my\s+|all\s+|all\s+the\s+)?files?\b",
        re.I,
    ),
    re.compile(r"\bwhat\s+files\b", re.I),
    re.compile(
        r"\b[\w-]+\.(?:py|txt|md|json|csv|toml|yaml|yml|ini|log)\b", re.I
    ),
)

_RESEARCH = (
    re.compile(
        r"\b(?:latest|today|tonight|yesterday|news|current|currently|right now|"
        r"weather|price|stock|score|who won|search the web|web search|look up|"
        r"google)\b",
        re.I,
    ),
    re.compile(r"\b(?:calculate|calculator|calculation|compute)\b", re.I),
    # 12 * 7, 3^4, 10 / 2, 9 - 4, 3 x 4, 15% of 200. Dates like 2026-10-09 and
    # 10/09/2026 do not match because - x / need spaces around them.
    re.compile(r"\d\s*[+*×^]\s*\d|\d\s+[-x/]\s+\d|\d\s*%\s*of\b", re.I),
)

_RULES = (
    ("notes", _NOTES),
    ("files", _FILES),
    ("researcher", _RESEARCH),
)


def route(text):
    """Return an agent name for this question, or None if no rule matches."""
    if not isinstance(text, str):
        return None
    cleaned = _URL.sub(" ", text)
    for agent_name, patterns in _RULES:
        if any(p.search(cleaned) for p in patterns):
            return agent_name
    return None