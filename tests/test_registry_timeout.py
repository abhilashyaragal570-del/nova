import time

from tools.base import Tool, ToolResult
from tools.policy import ToolPolicy
from tools.registry import DEFAULT_TIMEOUT_SECONDS, ToolRegistry


class SleepyTool(Tool):
    name = "sleepy"
    read_only = True
    parameters = {"type": "object", "properties": {}, "required": []}

    def __init__(self, seconds, timeout_seconds=None):
        self.seconds = seconds
        if timeout_seconds is not None:
            self.timeout_seconds = timeout_seconds

    def run(self, **kwargs) -> ToolResult:
        time.sleep(self.seconds)
        return ToolResult.success("done")


class CrashTool(Tool):
    name = "crash"
    read_only = True
    parameters = {"type": "object", "properties": {}, "required": []}

    def run(self, **kwargs) -> ToolResult:
        raise RuntimeError("boom")


class WriteTool(Tool):
    name = "writer"
    read_only = False
    parameters = {"type": "object", "properties": {}, "required": []}

    def run(self, **kwargs) -> ToolResult:
        return ToolResult.success("wrote")


def test_default_timeout_is_set():
    assert ToolRegistry().default_timeout == DEFAULT_TIMEOUT_SECONDS


def test_fast_tool_runs_normally():
    reg = ToolRegistry(default_timeout=1)
    reg.register(SleepyTool(0.01))
    result = reg.execute("sleepy", {})
    assert result.ok and result.output == "done"


def test_slow_tool_times_out():
    reg = ToolRegistry(default_timeout=0.1)
    reg.register(SleepyTool(1.0))
    result = reg.execute("sleepy", {})
    assert not result.ok and "timed out" in result.error


def test_timeout_returns_quickly():
    reg = ToolRegistry(default_timeout=0.1)
    reg.register(SleepyTool(1.0))
    start = time.monotonic()
    reg.execute("sleepy", {})
    assert time.monotonic() - start < 0.8  # did not wait for the tool to finish


def test_per_tool_timeout_overrides_default():
    reg = ToolRegistry(default_timeout=5)
    reg.register(SleepyTool(1.0, timeout_seconds=0.1))
    result = reg.execute("sleepy", {})
    assert not result.ok and "timed out" in result.error


def test_none_disables_timeout():
    reg = ToolRegistry(default_timeout=None)
    reg.register(SleepyTool(0.2))
    assert reg.execute("sleepy", {}).ok


def test_exception_is_still_contained():
    reg = ToolRegistry(default_timeout=1)
    reg.register(CrashTool())
    result = reg.execute("crash", {})
    assert not result.ok and "boom" in result.error


def test_confirmation_time_is_not_counted():
    # The user takes 0.3s to answer; the timeout is 0.1s; the tool is instant.
    def slow_confirm(name, args):
        time.sleep(0.3)
        return True

    reg = ToolRegistry(policy=ToolPolicy(confirm=slow_confirm), default_timeout=0.1)
    reg.register(WriteTool())
    assert reg.execute("writer", {}).ok