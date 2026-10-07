import pytest

from tools.calculator import CalculatorTool
from tools.registry import ToolRegistry


def calc(expression):
    return CalculatorTool().run(expression=expression)


# ---------- correct math ----------

def test_the_headline_example():
    result = calc("458 * 923")
    assert result.ok and result.output == 422734


@pytest.mark.parametrize(
    "expression, expected",
    [
        ("1 + 2", 3),
        ("10 - 4", 6),
        ("6 * 7", 42),
        ("10 / 4", 2.5),
        ("10 // 3", 3),
        ("10 % 3", 1),
        ("2 ** 10", 1024),
        ("(2 + 3) * 4", 20),
        ("-5 + 8", 3),
        ("2 * -3", -6),
        ("  7 + 1  ", 8),
    ],
)
def test_valid_expressions(expression, expected):
    result = calc(expression)
    assert result.ok and result.output == expected


# ---------- clean failures ----------

def test_division_by_zero():
    result = calc("1 / 0")
    assert not result.ok and "zero" in result.error.lower()


def test_empty_expression():
    assert not calc("").ok
    assert not calc("   ").ok


def test_non_string_input():
    assert not CalculatorTool().run(expression=123).ok
    assert not CalculatorTool().run(expression=None).ok


def test_expression_too_long():
    result = calc("1+" * 150 + "1")
    assert not result.ok and "too long" in result.error.lower()


def test_huge_exponent_rejected():
    result = calc("9 ** 9 ** 9")
    assert not result.ok


def test_exponent_limit_boundary():
    assert calc("2 ** 100").ok
    assert not calc("2 ** 101").ok


# ---------- security: things that must NOT run ----------

@pytest.mark.parametrize(
    "malicious",
    [
        "__import__('os').system('echo hacked')",
        "open('history.json').read()",
        "eval('1+1')",
        "exec('x = 1')",
        "().__class__.__bases__",
        "[x for x in range(3)]",
        "lambda: 1",
        "'a' * 3",
        "True + 1",
        "1 if True else 2",
        "x + 1",
        "1; 2",
        "import os",
        "1 < 2",
        "not 1",
        "~5",
    ],
)
def test_malicious_or_unsupported_input_is_rejected(malicious):
    result = calc(malicious)
    assert not result.ok
    assert result.error


# ---------- works through the registry ----------

def test_works_through_registry():
    reg = ToolRegistry()
    reg.register(CalculatorTool())
    result = reg.execute("calculator", {"expression": "458 * 923"})
    assert result.ok and result.output == 422734


def test_registry_reports_missing_argument():
    reg = ToolRegistry()
    reg.register(CalculatorTool())
    result = reg.execute("calculator", {})
    assert not result.ok and "expression" in result.error