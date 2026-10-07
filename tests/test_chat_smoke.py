import ast
from pathlib import Path

CHAT = Path(__file__).resolve().parent.parent / "app" / "chat.py"


def _source():
    return CHAT.read_text(encoding="utf-8")


def _main_function():
    tree = ast.parse(_source())
    return next(
        n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "main"
    )


def test_chat_file_parses():
    ast.parse(_source())


def test_main_contains_the_input_loop():
    # The truncated file had a main() that ended after one bare name.
    assert any(isinstance(n, ast.While) for n in _main_function().body)


def test_main_guard_is_present():
    assert 'if __name__ == "__main__":' in _source()


def test_api_request_is_registered():
    assert "registry.register(ApiRequestTool())" in _source()