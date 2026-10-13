"""Where Nova keeps its two small state files.

history.json (the main chat) and personality.json (the edited system prompt)
live in the folder named by NOVA_STATE_DIR. When the variable is unset or
empty, they stay in the current folder, as before. The Docker image sets it
to /app/state so a volume can keep both files.
"""
import os
from pathlib import Path


def state_path(name):
    folder = os.environ.get("NOVA_STATE_DIR", "").strip()
    return Path(folder) / name if folder else Path(name)