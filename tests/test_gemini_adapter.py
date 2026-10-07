from tools.calculator import CalculatorTool
from tools.gemini_adapter import to_function_declaration, to_gemini_tool
from tools.registry import ToolRegistry


def test_declaration_carries_name_and_description():
    decl = to_function_declaration(CalculatorTool())
    assert decl.name == "calculator"
    assert "mathematical expression" in decl.description


def test_declaration_carries_parameter_schema():
    decl = to_function_declaration(CalculatorTool())
    schema = decl.parameters_json_schema
    assert schema["required"] == ["expression"]
    assert "expression" in schema["properties"]


def test_gemini_tool_bundles_registered_tools():
    reg = ToolRegistry()
    reg.register(CalculatorTool())
    gemini_tool = to_gemini_tool(reg)
    assert len(gemini_tool.function_declarations) == 1
    assert gemini_tool.function_declarations[0].name == "calculator"


def test_empty_registry_returns_none():
    assert to_gemini_tool(ToolRegistry()) is None