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