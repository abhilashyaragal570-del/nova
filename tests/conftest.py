import os

# Tests never call Gemini, but config/settings.py refuses to import
# without a key. A fake one keeps the tests working where there is no .env
# (for example on GitHub Actions).
os.environ.setdefault("GEMINI_API_KEY", "test-key")
import pytest


@pytest.fixture(autouse=True)
def isolated_usage_log(tmp_path, monkeypatch):
    """Send usage logging to a temp file so tests never touch the real logs/."""
    monkeypatch.setenv("TOOL_LOG_PATH", str(tmp_path / "usage_test.jsonl"))


@pytest.fixture(autouse=True)
def tracing_off(monkeypatch):
    """Keep tracing off in tests, whatever the shell has set.

    Without this, a leftover NOVA_TRACING in the terminal made the tests write
    fake spans into the real trace file. The tracing module is also reset
    before and after each test, so one test's setup never leaks into the next.
    """
    from app import tracing

    monkeypatch.delenv("NOVA_TRACING", raising=False)
    monkeypatch.delenv("NOVA_TRACE_FILE", raising=False)
    tracing.reset()
    yield
    tracing.reset()