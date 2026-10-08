"""PostgreSQL version of ConversationStore.

Same methods as memory.conversation_store.ConversationStore, so callers
don't change. All chats, including "main", are rows in one table.
"""
import uuid

import psycopg
from psycopg.types.json import Jsonb

from memory.conversation_store import MAIN_ID, MAIN_TITLE, NEW_TITLE, ConversationStore

_SCHEMA = """
CREATE TABLE IF NOT EXISTS conversations (
    id          TEXT PRIMARY KEY,
    title       TEXT NOT NULL,
    messages    JSONB NOT NULL DEFAULT '[]'::jsonb,
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
)
"""


def _clean(messages):
    if not isinstance(messages, list):
        return []
    return [m for m in messages if isinstance(m, dict) and m.get("text")]


class PostgresConversationStore:
    def __init__(self, database_url):
        self.database_url = database_url
        with psycopg.connect(self.database_url) as conn:
            conn.execute(_SCHEMA)

    @staticmethod
    def is_valid_id(cid):
        return ConversationStore.is_valid_id(cid)

    def create(self, title=NEW_TITLE):
        cid = uuid.uuid4().hex[:12]
        self.save(cid, title, [])
        return cid

    def load(self, cid):
        """Return {'title', 'messages'}, or None if the id is invalid or unknown."""
        if not self.is_valid_id(cid):
            return None
        with psycopg.connect(self.database_url) as conn:
            row = conn.execute(
                "SELECT title, messages FROM conversations WHERE id = %s", (cid,)
            ).fetchone()
        if cid == MAIN_ID:
            return {"title": MAIN_TITLE, "messages": _clean(row[1] if row else [])}
        if row is None:
            return None
        return {"title": str(row[0] or NEW_TITLE), "messages": _clean(row[1])}

    def save(self, cid, title, messages):
        if not self.is_valid_id(cid):
            raise ValueError(f"invalid conversation id: {cid!r}")
        if cid == MAIN_ID:
            title = MAIN_TITLE
        with psycopg.connect(self.database_url) as conn:
            conn.execute(
                """
                INSERT INTO conversations (id, title, messages, updated_at)
                VALUES (%s, %s, %s, now())
                ON CONFLICT (id) DO UPDATE
                SET title = EXCLUDED.title,
                    messages = EXCLUDED.messages,
                    updated_at = now()
                """,
                (cid, title, Jsonb(messages)),
            )

    def delete(self, cid):
        """Delete a chat. Returns False for an invalid id, True otherwise."""
        if not self.is_valid_id(cid):
            return False
        with psycopg.connect(self.database_url) as conn:
            conn.execute("DELETE FROM conversations WHERE id = %s", (cid,))
        return True

    def list_conversations(self):
        """Main chat first, then the others, newest first."""
        items = [{"id": MAIN_ID, "title": MAIN_TITLE}]
        with psycopg.connect(self.database_url) as conn:
            rows = conn.execute(
                "SELECT id, title FROM conversations "
                "WHERE id <> %s ORDER BY updated_at DESC",
                (MAIN_ID,),
            ).fetchall()
        for cid, title in rows:
            if self.is_valid_id(cid):
                items.append({"id": cid, "title": str(title or NEW_TITLE)})
        return items