"""Conversation storage.

ConversationStore is the one place that reads and writes saved chats. Callers
use its methods and never open chat files themselves, so the storage behind it
can change (files now, PostgreSQL later) without touching them.

Two kinds of chat exist:
  - "main": a list of messages in history_file (shared with the terminal chat).
  - every other chat: one JSON file <id>.json in conv_dir, holding a title
    and a list of messages.
"""
import json
import re
import uuid
from pathlib import Path

MAIN_ID = "main"
MAIN_TITLE = "Main chat"
NEW_TITLE = "New chat"
_ID_PATTERN = re.compile(r"[0-9a-f]{12}")


class ConversationStore:
    def __init__(self, conv_dir="conversations", history_file="history.json"):
        self.conv_dir = Path(conv_dir)
        self.history_file = Path(history_file)

    @staticmethod
    def is_valid_id(cid):
        """Only 'main' or 12 lowercase hex characters, which blocks '../x' tricks."""
        if cid == MAIN_ID:
            return True
        return isinstance(cid, str) and _ID_PATTERN.fullmatch(cid) is not None

    def create(self, title=NEW_TITLE):
        cid = uuid.uuid4().hex[:12]
        self.save(cid, title, [])
        return cid

    def load(self, cid):
        """Return {'title', 'messages'}, or None if the id is invalid or unknown."""
        if not self.is_valid_id(cid):
            return None
        if cid == MAIN_ID:
            return {"title": MAIN_TITLE, "messages": self._read_main()}
        path = self._path(cid)
        if not path.exists():
            return None
        return self._read_file(path)

    def save(self, cid, title, messages):
        if not self.is_valid_id(cid):
            raise ValueError(f"invalid conversation id: {cid!r}")
        if cid == MAIN_ID:
            self.history_file.write_text(
                json.dumps(messages, indent=2, ensure_ascii=False), encoding="utf-8"
            )
            return
        self.conv_dir.mkdir(parents=True, exist_ok=True)
        self._path(cid).write_text(
            json.dumps(
                {"title": title, "messages": messages}, indent=2, ensure_ascii=False
            ),
            encoding="utf-8",
        )

    def delete(self, cid):
        """Delete a chat. Returns False for an invalid id, True otherwise."""
        if not self.is_valid_id(cid):
            return False
        if cid == MAIN_ID:
            self.history_file.unlink(missing_ok=True)
        else:
            self._path(cid).unlink(missing_ok=True)
        return True

    def list_conversations(self):
        """Main chat first, then the others, newest first."""
        items = [{"id": MAIN_ID, "title": MAIN_TITLE}]
        if not self.conv_dir.exists():
            return items
        files = sorted(
            self.conv_dir.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True
        )
        for f in files:
            if not self.is_valid_id(f.stem):
                continue
            data = self._read_file(f)
            if data:
                items.append({"id": f.stem, "title": data["title"]})
        return items

    def _path(self, cid):
        return self.conv_dir / f"{cid}.json"

    @staticmethod
    def _read_file(path):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return {
                "title": str(data.get("title") or NEW_TITLE),
                "messages": [m for m in data.get("messages", []) if m.get("text")],
            }
        except (OSError, json.JSONDecodeError, AttributeError):
            return None

    def _read_main(self):
        try:
            data = json.loads(self.history_file.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return []
        if not isinstance(data, list):
            return []
        return [m for m in data if isinstance(m, dict) and m.get("text")]