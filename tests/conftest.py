import os

# Tests never call Gemini, but config/settings.py refuses to import
# without a key. A fake one keeps the tests working where there is no .env
# (for example on GitHub Actions).
os.environ.setdefault("GEMINI_API_KEY", "test-key")
