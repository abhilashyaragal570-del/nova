import pytest

from tools.base import Tool, ToolResult
from tools.policy import ToolPolicy


class ReadTool(Tool):
    name = "reader"
    read_only = True

    def run(self, **kwargs) -> ToolResult:
        return ToolResult.success("ok")


class WriteTool(Tool):
    name = "writer"
    read_only = False

    def run(self, **kwargs) -> ToolResult:
        return ToolResult.success("ok")


# ---------- blocklist and allowlist ----------

def test_read_only_tool_allowed_by_default():
    assert ToolPolicy().check(ReadTool(), {}) is None


def test_blocked_tool_refused():
    reason = ToolPolicy(blocked={"reader"}).check(ReadTool(), {})
    assert reason and "blocked" in reason


def test_blocklist_beats_allowlist():
    policy = ToolPolicy(allowed={"reader"}, blocked={"reader"})
    assert policy.check(ReadTool(), {}) is not None


def test_allowlist_refuses_unlisted_tool():
    reason = ToolPolicy(allowed={"other"}).check(ReadTool(), {})
    assert reason and "allowed list" in reason


def test_allowlist_permits_listed_tool():
    assert ToolPolicy(allowed={"reader"}).check(ReadTool(), {}) is None


def test_empty_allowlist_refuses_everything():
    assert ToolPolicy(allowed=set()).check(ReadTool(), {}) is not None


# ---------- confirmation for non-read-only tools ----------

def test_write_tool_without_handler_fails_closed():
    reason = ToolPolicy().check(WriteTool(), {})
    assert reason and "confirmation" in reason


def test_write_tool_approved():
    policy = ToolPolicy(confirm=lambda name, args: True)
    assert policy.check(WriteTool(), {}) is None


def test_write_tool_declined():
    policy = ToolPolicy(confirm=lambda name, args: False)
    reason = policy.check(WriteTool(), {})
    assert reason and "declined" in reason


@pytest.mark.parametrize("not_quite_yes", ["yes", 1, None])
def test_only_literal_true_approves(not_quite_yes):
    policy = ToolPolicy(confirm=lambda name, args: not_quite_yes)
    assert policy.check(WriteTool(), {}) is not None


def test_confirm_exception_denies():
    def boom(name, args):
        raise RuntimeError("handler crashed")

    reason = ToolPolicy(confirm=boom).check(WriteTool(), {})
    assert reason and "failed" in reason


def test_confirm_not_called_for_read_only_tool():
    asked = []
    policy = ToolPolicy(confirm=lambda name, args: asked.append(name) or True)
    assert policy.check(ReadTool(), {}) is None
    assert asked == []


def test_confirm_receives_name_and_arguments():
    seen = []
    policy = ToolPolicy(confirm=lambda name, args: seen.append((name, args)) or True)
    policy.check(WriteTool(), {"path": "a.txt"})
    assert seen == [("writer", {"path": "a.txt"})]


def test_blocked_write_tool_never_asks_user():
    asked = []
    policy = ToolPolicy(blocked={"writer"}, confirm=lambda n, a: asked.append(n) or True)
    assert policy.check(WriteTool(), {}) is not None
    assert asked == []