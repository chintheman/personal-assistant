"""
Database layer — SQLite via aiosqlite.
All schema init, queries, and mutations live here.
Business logic lives in core/.
"""

import aiosqlite
import os
from datetime import datetime
from pathlib import Path

DB_PATH = os.getenv("PA_DB_PATH", "data/pa.db")


class _DBContext:
    """Async context manager that opens + configures a DB connection per call."""
    async def __aenter__(self) -> aiosqlite.Connection:
        Path(DB_PATH).parent.mkdir(parents=True, exist_ok=True)
        self._db = await aiosqlite.connect(DB_PATH)
        self._db.row_factory = aiosqlite.Row
        await self._db.execute("PRAGMA journal_mode=WAL")
        await self._db.execute("PRAGMA foreign_keys=ON")
        return self._db

    async def __aexit__(self, *args):
        await self._db.close()


def get_db() -> _DBContext:
    return _DBContext()


async def init_db():
    """Create all tables on first run. Idempotent."""
    from core.conversation import init_conversation_table
    await init_conversation_table()

    async with get_db() as db:
        await db.executescript("""
            CREATE TABLE IF NOT EXISTS ideas (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                text        TEXT NOT NULL,
                summary     TEXT,
                tags        TEXT,          -- comma-separated
                captured_at TEXT NOT NULL,
                shown_count INTEGER DEFAULT 0,
                last_shown  TEXT,
                archived    INTEGER DEFAULT 0
            );

            CREATE TABLE IF NOT EXISTS links (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                url         TEXT NOT NULL,
                title       TEXT,
                summary     TEXT,
                tags        TEXT,
                captured_at TEXT NOT NULL,
                shown_count INTEGER DEFAULT 0,
                last_shown  TEXT,
                archived    INTEGER DEFAULT 0,
                read        INTEGER DEFAULT 0
            );

            CREATE TABLE IF NOT EXISTS digest_log (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                sent_at    TEXT NOT NULL,
                item_type  TEXT NOT NULL,  -- 'idea' | 'link'
                item_id    INTEGER NOT NULL,
                action     TEXT DEFAULT 'shown'  -- 'shown' | 'archived' | 'snoozed'
            );

            CREATE TABLE IF NOT EXISTS snoozes (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                item_type  TEXT NOT NULL,
                item_id    INTEGER NOT NULL,
                wake_at    TEXT NOT NULL,
                resolved   INTEGER DEFAULT 0
            );
        """)
        await db.commit()


# ─── IDEAS ─────────────────────────────────────────────────────────────────────

async def insert_idea(text: str, summary: str | None, tags: str) -> int:
    async with get_db() as db:
        cur = await db.execute(
            "INSERT INTO ideas (text, summary, tags, captured_at) VALUES (?,?,?,?)",
            (text, summary, tags, datetime.utcnow().isoformat()),
        )
        await db.commit()
        return cur.lastrowid


async def get_active_ideas(limit: int = 10) -> list[dict]:
    """Return un-archived ideas sorted: never-shown first, then oldest last-shown."""
    async with get_db() as db:
        cur = await db.execute("""
            SELECT i.*
            FROM ideas i
            LEFT JOIN snoozes s ON s.item_type='idea' AND s.item_id=i.id AND s.resolved=0
            WHERE i.archived=0
              AND (s.wake_at IS NULL OR s.wake_at <= ?)
            ORDER BY i.shown_count ASC, i.captured_at ASC
            LIMIT ?
        """, (datetime.utcnow().isoformat(), limit))
        rows = await cur.fetchall()
        return [dict(r) for r in rows]


async def archive_idea(idea_id: int):
    async with get_db() as db:
        await db.execute("UPDATE ideas SET archived=1 WHERE id=?", (idea_id,))
        await db.commit()


async def mark_idea_shown(idea_id: int):
    async with get_db() as db:
        await db.execute(
            "UPDATE ideas SET shown_count=shown_count+1, last_shown=? WHERE id=?",
            (datetime.utcnow().isoformat(), idea_id),
        )
        await db.commit()


async def search_ideas(query: str) -> list[dict]:
    async with get_db() as db:
        cur = await db.execute(
            "SELECT * FROM ideas WHERE archived=0 AND (text LIKE ? OR tags LIKE ? OR summary LIKE ?)",
            (f"%{query}%", f"%{query}%", f"%{query}%"),
        )
        rows = await cur.fetchall()
        return [dict(r) for r in rows]


# ─── LINKS ─────────────────────────────────────────────────────────────────────

async def insert_link(url: str, title: str | None, summary: str | None, tags: str) -> int:
    async with get_db() as db:
        cur = await db.execute(
            "INSERT INTO links (url, title, summary, tags, captured_at) VALUES (?,?,?,?,?)",
            (url, title, summary, tags, datetime.utcnow().isoformat()),
        )
        await db.commit()
        return cur.lastrowid


async def get_active_links(limit: int = 10) -> list[dict]:
    async with get_db() as db:
        cur = await db.execute("""
            SELECT l.*
            FROM links l
            LEFT JOIN snoozes s ON s.item_type='link' AND s.item_id=l.id AND s.resolved=0
            WHERE l.archived=0 AND l.read=0
              AND (s.wake_at IS NULL OR s.wake_at <= ?)
            ORDER BY l.shown_count ASC, l.captured_at ASC
            LIMIT ?
        """, (datetime.utcnow().isoformat(), limit))
        rows = await cur.fetchall()
        return [dict(r) for r in rows]


async def archive_link(link_id: int):
    async with get_db() as db:
        await db.execute("UPDATE links SET archived=1 WHERE id=?", (link_id,))
        await db.commit()


async def mark_link_read(link_id: int):
    async with get_db() as db:
        await db.execute("UPDATE links SET read=1 WHERE id=?", (link_id,))
        await db.commit()


async def mark_link_shown(link_id: int):
    async with get_db() as db:
        await db.execute(
            "UPDATE links SET shown_count=shown_count+1, last_shown=? WHERE id=?",
            (datetime.utcnow().isoformat(), link_id),
        )
        await db.commit()


async def search_links(query: str) -> list[dict]:
    async with get_db() as db:
        cur = await db.execute(
            "SELECT * FROM links WHERE archived=0 AND (url LIKE ? OR summary LIKE ? OR tags LIKE ?)",
            (f"%{query}%", f"%{query}%", f"%{query}%"),
        )
        rows = await cur.fetchall()
        return [dict(r) for r in rows]


# ─── SNOOZES ───────────────────────────────────────────────────────────────────

async def snooze_item(item_type: str, item_id: int, wake_at: datetime):
    async with get_db() as db:
        # resolve any existing snooze for this item first
        await db.execute(
            "UPDATE snoozes SET resolved=1 WHERE item_type=? AND item_id=? AND resolved=0",
            (item_type, item_id),
        )
        await db.execute(
            "INSERT INTO snoozes (item_type, item_id, wake_at) VALUES (?,?,?)",
            (item_type, item_id, wake_at.isoformat()),
        )
        await db.commit()


async def get_due_snoozes() -> list[dict]:
    async with get_db() as db:
        cur = await db.execute(
            "SELECT * FROM snoozes WHERE resolved=0 AND wake_at <= ?",
            (datetime.utcnow().isoformat(),),
        )
        rows = await cur.fetchall()
        return [dict(r) for r in rows]


# ─── DIGEST LOG ────────────────────────────────────────────────────────────────

async def log_digest_item(item_type: str, item_id: int, action: str = "shown"):
    async with get_db() as db:
        await db.execute(
            "INSERT INTO digest_log (sent_at, item_type, item_id, action) VALUES (?,?,?,?)",
            (datetime.utcnow().isoformat(), item_type, item_id, action),
        )
        await db.commit()
