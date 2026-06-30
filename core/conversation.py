"""
Conversation history store — per chat_id rolling window.
Persisted in SQLite so the agent has memory across restarts.
"""

import json
from datetime import datetime
from core.db import get_db

MAX_HISTORY = 20  # messages kept per chat (rolling window)


async def init_conversation_table():
    """Call once at startup — idempotent."""
    async with get_db() as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS conversation_history (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_id    TEXT NOT NULL,
                role       TEXT NOT NULL,   -- 'user' | 'assistant' | 'tool'
                content    TEXT NOT NULL,   -- JSON-encoded (for tool calls) or plain text
                ts         TEXT NOT NULL
            )
        """)
        await db.execute(
            "CREATE INDEX IF NOT EXISTS idx_conv_chat_id ON conversation_history(chat_id, id)"
        )
        await db.commit()


async def get_history(chat_id: str) -> list[dict]:
    """Return the last MAX_HISTORY messages for this chat."""
    async with get_db() as db:
        cur = await db.execute(
            """
            SELECT role, content FROM conversation_history
            WHERE chat_id = ?
            ORDER BY id DESC
            LIMIT ?
            """,
            (str(chat_id), MAX_HISTORY),
        )
        rows = await cur.fetchall()
    # rows are newest-first; reverse to chronological
    result = []
    for row in reversed(rows):
        role, content = row[0], row[1]
        try:
            # Tool result content may be JSON-encoded list/dict
            parsed = json.loads(content)
            result.append({"role": role, "content": parsed})
        except (json.JSONDecodeError, TypeError):
            result.append({"role": role, "content": content})
    return result


async def append_message(chat_id: str, role: str, content):
    """Append one message to the history. content can be str or list (for tool calls)."""
    if not isinstance(content, str):
        content = json.dumps(content)
    async with get_db() as db:
        await db.execute(
            "INSERT INTO conversation_history (chat_id, role, content, ts) VALUES (?,?,?,?)",
            (str(chat_id), role, content, datetime.utcnow().isoformat()),
        )
        await db.commit()


async def clear_old_history(chat_id: str):
    """Keep only the newest MAX_HISTORY messages, prune the rest."""
    async with get_db() as db:
        await db.execute(
            """
            DELETE FROM conversation_history
            WHERE chat_id = ?
              AND id NOT IN (
                SELECT id FROM conversation_history
                WHERE chat_id = ?
                ORDER BY id DESC
                LIMIT ?
              )
            """,
            (str(chat_id), str(chat_id), MAX_HISTORY),
        )
        await db.commit()
