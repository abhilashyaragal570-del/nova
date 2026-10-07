"""Safe calculator tool. Uses an AST allowlist instead of eval()."""
import ast
import operator
from typing import Any

from tools.base import Tool, ToolResult

MAX_EXPRESSION_LENGTH = 200
MAX_EXPONENT = 100

_BINARY_OPS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
}

_UNARY_OPS = {
    ast.UAdd: operator.pos,
    ast.USub: operator.neg,
}


def _evaluate(node: ast.AST) -> float | int:
    if isinstance(node, ast.Expression):
        return _evaluate(node.body)

    if isinstance(node, ast.Constant):
        # bool is a subclass of int, so exclude it explicitly
        if isinstance(node.value, (int, float)) and not isinstance(node.value, bool):
            return node.value
        raise ValueError("Only numbers are allowed")

    if isinstance(node, ast.BinOp):
        op = _BINARY_OPS.get(type(node.op))
        if op is None:
            raise ValueError("Operator not allowed")
        left = _evaluate(node.left)
        right = _evaluate(node.right)
        if isinstance(node.op, ast.Pow) and abs(right) > MAX_EXPONENT:
            raise ValueError(f"Exponent too large (max {MAX_EXPONENT})")
        return op(left, right)

    if isinstance(node, ast.UnaryOp):
        op = _UNARY_OPS.get(type(node.op))
        if op is None:
            raise ValueError("Operator not allowed")
        return op(_evaluate(node.operand))

    raise ValueError("Unsupported expression")


class CalculatorTool(Tool):
    name = "calculator"
    description = (
        "Evaluates a mathematical expression and returns the exact result. "
        "Supports + - * / // % ** and parentheses. "
        "Use this for any arithmetic instead of calculating yourself."
    )
    parameters = {
        "type": "object",
        "properties": {
            "expression": {
                "type": "string",
                "description": "The expression to evaluate, e.g. '458 * 923'.",
            }
        },
        "required": ["expression"],
    }
    read_only = True

    def run(self, expression: Any = None, **_: Any) -> ToolResult:
        if not isinstance(expression, str) or not expression.strip():
            return ToolResult.failure("expression must be a non-empty string")
        if len(expression) > MAX_EXPRESSION_LENGTH:
            return ToolResult.failure(
                f"Expression too long (max {MAX_EXPRESSION_LENGTH} characters)"
            )
        try:
            tree = ast.parse(expression.strip(), mode="eval")
            return ToolResult.success(_evaluate(tree))
        except ZeroDivisionError:
            return ToolResult.failure("Division by zero")
        except (SyntaxError, ValueError) as e:
            return ToolResult.failure(f"Invalid expression: {e}")
        except OverflowError:
            return ToolResult.failure("Result too large")