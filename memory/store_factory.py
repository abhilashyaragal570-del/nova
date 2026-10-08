"""Pick the conversation store: PostgreSQL if DATABASE_URL is set, else files."""
import os

from dotenv import load_dotenv

from memory.conversation_store import ConversationStore


def create_store():
    load_dotenv()
    url = os.environ.get("DATABASE_URL")
    if url:
        from memory.postgres_store import PostgresConversationStore

        return PostgresConversationStore(url)
    return ConversationStore()