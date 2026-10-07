import pytest

from app.confirm import confirm_in_terminal
from tools.base import Tool, ToolResult
from tools.policy import ToolPolicy


def ask(answer, arguments=None, name="write_file"):
    """Run the prompt with a fake keyboard; return (decision, screen_text)."""
    lines = []

    def fake_input(prompt):
        lines.append(prompt)
        if isinstance(answer, BaseException):
            raise answer
        return answer

    decision = confirm_in_terminal(
        name, arguments or {}, input_fn=fake_input, output_fn=lines.append
    )
    return decision, "\n".join(str(x) for x in lines)


# ---------- approval ----------

def test_y_approves():
    assert ask("y")[0] is True


def test_yes_approves():
    assert ask("yes")[0] is True


def test_case_and_spaces_are_ignored():
    assert ask("  Y  ")[0] is True


# ---------- everything else refuses ----------

@pytest.mark.parametrize("answer", ["", " ", "n", "no", "maybe", "yy", "yes please"])
def test_unclear_answers_refuse(answer):
    assert ask(answer)[0] is False


def test_closed_input_refuses():
    assert ask(EOFError())[0] is False


def test_ctrl_c_refuses():
    assert ask(KeyboardInterrupt())[0] is False


def test_non_string_answer_refuses():
    assert ask(None)[0] is False


# ---------- what the user sees ----------

def test_shows_tool_name_and_arguments():
    _, screen = ask("n", {"path": "report.md", "content": "hello"})
    assert "write_file" in screen
    assert "report.md" in screen
    assert "hello" in screen


def test_long_content_is_truncated():
    _, screen = ask("n", {"content": "x" * 5000})
    assert "x" * 5000 not in screen
    assert "more characters" in screen


def test_control_characters_are_made_visible():
    _, screen = ask("n", {"content": "\x1b[31mred"})
    assert "\x1b" not in screen  # the raw escape code never reaches the terminal
    assert "\\x1b" in screen     # it is shown as readable text instead


# ---------- works as a policy confirmation handler ----------

class WriteTool(Tool):
    name = "writer"
    read_only = False

    def run(self, **kwargs) -> ToolResult:
        return ToolResult.success("ok")


def test_plugs_into_policy():
    approve = ToolPolicy(
        confirm=lambda n, a: confirm_in_terminal(
            n, a, input_fn=lambda p: "y", output_fn=lambda s: None
        )
    )
    assert approve.check(WriteTool(), {"path": "a.txt"}) is None

    refuse = ToolPolicy(
        confirm=lambda n, a: confirm_in_terminal(
            n, a, input_fn=lambda p: "", output_fn=lambda s: None
        )
    )
    assert refuse.check(WriteTool(), {"path": "a.txt"}) is not None