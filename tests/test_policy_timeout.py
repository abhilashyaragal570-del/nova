from tools.base import Tool, ToolResult
from tools.policy import ConfirmTimeout, ToolPolicy
from tools.registry import ToolRegistry
from web.approvals import ApprovalBroker


class Counter:
    runs = 0


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


def times_out(name, args):
    raise ConfirmTimeout("nobody answered")


def test_a_timeout_says_timed_out_not_declined():
    reason = ToolPolicy(confirm=times_out).check(WriteTool(), {"path": "a.txt"})
    assert reason is not None
    assert "timed out" in reason
    assert "declined" not in reason


def test_a_real_denial_still_says_declined():
    reason = ToolPolicy(confirm=lambda n, a: False).check(WriteTool(), {})
    assert reason and "declined" in reason


def test_a_timeout_never_runs_the_tool_and_is_marked_refused():
    Counter.runs = 0
    registry = ToolRegistry(policy=ToolPolicy(confirm=times_out))
    registry.register(WriteTool())
    result = registry.execute("writer", {"path": "a.txt"})
    assert result.ok is False
    assert result.refused is True
    assert "timed out" in result.error
    assert Counter.runs == 0


def test_the_real_broker_timeout_reaches_the_policy():
    broker = ApprovalBroker(timeout=0.05)
    reason = ToolPolicy(confirm=broker.confirm).check(WriteTool(), {"path": "a.txt"})
    assert reason and "timed out" in reason
    assert broker.list_pending() == []