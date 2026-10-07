from tools.base import Tool, ToolResult
from tools.registry import ToolRegistry


class EchoTool(Tool):
    name = "echo"
    description = "Returns the text it is given."
    parameters = {
        "type": "object",
        "properties": {"text": {"type": "string"}},
        "required": ["text"],
    }

    def run(self, text: str) -> ToolResult:
        return ToolResult.success(text)


class BrokenTool(Tool):
    name = "broken"
    description = "Always raises."

    def run(self) -> ToolResult:
        raise RuntimeError("boom")


def make_registry():
    reg = ToolRegistry()
    reg.register(EchoTool())
    reg.register(BrokenTool())
    return reg


def test_execute_success():
    result = make_registry().execute("echo", {"text": "hi"})
    assert result.ok and result.output == "hi"


def test_unknown_tool():
    result = make_registry().execute("nope", {})
    assert not result.ok and "Unknown tool" in result.error


def test_missing_argument():
    result = make_registry().execute("echo", {})
    assert not result.ok and "text" in result.error


def test_tool_exception_is_contained():
    result = make_registry().execute("broken", {})
    assert not result.ok and "boom" in result.error


def test_duplicate_registration_rejected():
    reg = make_registry()
    try:
        reg.register(EchoTool())
        assert False, "expected ValueError"
    except ValueError:
        pass