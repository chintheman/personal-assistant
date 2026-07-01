"""
Todos pipeline.
Capture → categorize (tag) → infer priority (if unset) → parse due date/recurrence → store.
Recurrence: on completion, if recurring, auto-spawns the next occurrence.
"""

import os
import re
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from core.db import insert_todo, get_todo, complete_todo as _complete_todo_row
from core.llm import categorize, infer_priority

TZ = ZoneInfo(os.getenv("PA_TIMEZONE", "Asia/Singapore"))

WEEKDAYS = {"mon": 0, "tue": 1, "wed": 2, "thu": 3, "fri": 4, "sat": 5, "sun": 6}


def parse_due_date(raw: str | None) -> str | None:
    """Natural language or ISO8601 -> ISO8601 string in local TZ. None if unparseable/absent."""
    if not raw:
        return None
    now = datetime.now(TZ)
    t = raw.lower().strip()

    if "today" in t:
        dt = now.replace(hour=23, minute=59, second=0, microsecond=0)
    elif "tomorrow" in t:
        dt = (now + timedelta(days=1)).replace(hour=23, minute=59, second=0, microsecond=0)
    elif "next week" in t:
        dt = (now + timedelta(days=7)).replace(hour=23, minute=59, second=0, microsecond=0)
    else:
        dt = None
        m = re.search(r"(\d+)\s*day", t)
        if m:
            dt = (now + timedelta(days=int(m.group(1)))).replace(hour=23, minute=59, second=0, microsecond=0)
        else:
            for name, idx in WEEKDAYS.items():
                if name in t:
                    delta = (idx - now.weekday() + 7) % 7 or 7
                    dt = (now + timedelta(days=delta)).replace(hour=23, minute=59, second=0, microsecond=0)
                    break
        if dt is None:
            try:
                dt = datetime.fromisoformat(raw)
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=TZ)
            except Exception:
                return None

    return dt.astimezone(TZ).isoformat()


def parse_recurrence(raw: str | None) -> str | None:
    """Natural language -> normalized recurrence code, or None."""
    if not raw:
        return None
    t = raw.lower().strip()
    if not t or t in ("none", "no", "never"):
        return None
    if "daily" in t or "every day" in t:
        return "daily"
    if "weekday" in t:
        return "weekly:mon,tue,wed,thu,fri"
    if "monthly" in t or "every month" in t:
        return "monthly"
    days = [d for d in WEEKDAYS if d in t]
    if days:
        return "weekly:" + ",".join(days)
    if "week" in t:
        return "weekly"
    return None


def _next_due(due_at: str | None, recurrence: str) -> str:
    now = datetime.now(TZ)
    base = datetime.fromisoformat(due_at).astimezone(TZ) if due_at else now

    if recurrence == "daily":
        nxt = base + timedelta(days=1)
    elif recurrence == "monthly":
        month = base.month % 12 + 1
        year = base.year + (1 if base.month == 12 else 0)
        day = min(base.day, 28)
        nxt = base.replace(year=year, month=month, day=day)
    elif recurrence.startswith("weekly:"):
        days = [WEEKDAYS[d] for d in recurrence.split(":", 1)[1].split(",") if d in WEEKDAYS]
        if days:
            cur = base.weekday()
            deltas = sorted((d - cur) % 7 or 7 for d in days)
            nxt = base + timedelta(days=deltas[0])
        else:
            nxt = base + timedelta(days=7)
    else:  # plain "weekly"
        nxt = base + timedelta(days=7)

    if nxt <= now:
        nxt = now + timedelta(days=1)
    return nxt.isoformat()


async def capture_todo(text: str, due: str | None = None, priority: str | None = None,
                        recurrence: str | None = None) -> dict:
    """Full capture pipeline. Returns the stored record metadata."""
    tag = await categorize(text)
    if not priority:
        priority = await infer_priority(text)
    due_at = parse_due_date(due)
    rec = parse_recurrence(recurrence)

    todo_id = await insert_todo(text=text, tags=tag, priority=priority, due_at=due_at, recurrence=rec)
    return {"id": todo_id, "tag": tag, "priority": priority, "due_at": due_at, "recurrence": rec}


async def complete_todo(todo_id: int) -> dict:
    """Marks a todo done. If recurring, spawns the next occurrence."""
    todo = await get_todo(todo_id)
    if not todo:
        return {"ok": False}

    await _complete_todo_row(todo_id)

    next_id = None
    if todo.get("recurrence"):
        next_due = _next_due(todo.get("due_at"), todo["recurrence"])
        next_id = await insert_todo(
            text=todo["text"], tags=todo.get("tags"), priority=todo.get("priority", "medium"),
            due_at=next_due, recurrence=todo["recurrence"],
        )

    return {"ok": True, "next_id": next_id}
