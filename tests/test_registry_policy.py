from tools.base import Tool, ToolResult
from tools.policy import ToolPolicy
from tools.registry import ToolRegistry


class Counter:
    """Shared counter so tests can prove whether a tool actually ran."""
    runs = 0


class ReadTool(Tool):
    name = "reader"
    read_only = True
    parameters = {"type": "object", "properties": {}, "required": []}

    def run(self, **kwargs) -> ToolResult:
        Counter.runs += 1
        return ToolResult.success("read")


class WriteTool(Tool):
    name = "writer"
    read_only = False
    parameters = {
        "type": "object",
        "properties": {"path": {"type": "string"}},
        "required": ["path"],
    }

    def run(self, path, **kwargs) -> ToolResult:
        Counter.runs += 1
        return ToolResult.success(f"wrote {path}")


def make(policy=None):
    Counter.runs = 0
    reg = ToolRegistry(policy=policy)
    reg.register(ReadTool())
    reg.register(WriteTool())
    return reg


def test_no_policy_behaves_as_before():
    reg = make()
    assert reg.execute("reader", {}).ok
    assert reg.execute("writer", {"path": "a.txt"}).ok
    assert Counter.runs == 2


def test_blocked_tool_never_runs():
    reg = make(ToolPolicy(blocked={"reader"}))
    result = reg.execute("reader", {})
    assert not result.ok and "blocked" in result.error
    assert Counter.runs == 0


def test_not_allowed_tool_never_runs():
    reg = make(ToolPolicy(allowed={"writer"}, confirm=lambda n, a: True))
    result = reg.execute("reader", {})
    assert not result.ok and "allowed list" in result.error
    assert Counter.runs == 0


def test_write_tool_declined_never_runs():
    reg = make(ToolPolicy(confirm=lambda n, a: False))
    result = reg.execute("writer", {"path": "a.txt"})
    assert not result.ok and "declined" in result.error
    assert Counter.runs == 0


def test_write_tool_approved_runs():
    reg = make(ToolPolicy(confirm=lambda n, a: True))
    result = reg.execute("writer", {"path": "a.txt"})
    assert result.ok and Counter.runs == 1


def test_write_tool_without_handler_never_runs():
    reg = make(ToolPolicy())
    assert not reg.execute("writer", {"path": "a.txt"}).ok
    assert Counter.runs == 0


def test_read_only_tool_runs_without_asking():
    asked = []
    reg = make(ToolPolicy(confirm=lambda n, a: asked.append(n) or True))
    assert reg.execute("reader", {}).ok
    assert asked == []


def test_invalid_call_does_not_ask_user():
    asked = []
    reg = make(ToolPolicy(confirm=lambda n, a: asked.append(n) or True))
    result = reg.execute("writer", {})  # missing required 'path'
    assert not result.ok and "path" in result.error
    assert asked == []


def test_unknown_tool_does_not_ask_user():
    asked = []
    reg = make(ToolPolicy(confirm=lambda n, a: asked.append(n) or True))
    assert not reg.execute("nope", {}).ok
    assert asked == []


def test_confirm_sees_the_real_arguments():
    seen = []
    reg = make(ToolPolicy(confirm=lambda n, a: seen.append((n, a)) or True))
    reg.execute("writer", {"path": "report.md"})
    assert seen == [("writer", {"path": "report.md"})]