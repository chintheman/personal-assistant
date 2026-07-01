"""
Habit tracking — passive log + streaks.
User mentions a habit naturally ("did my workout") — no proactive prompts,
just normalized, logged for today (idempotent), and surfaced in the evening digest.
"""

import os
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from core.db import (
    find_habit_by_name, create_habit, log_habit as _log_habit_row,
    get_habit_logs, get_all_habits,
)
from core.llm import normalize_habit_name

TZ = ZoneInfo(os.getenv("PA_TIMEZONE", "Asia/Singapore"))


def _today_str() -> str:
    return datetime.now(TZ).strftime("%Y-%m-%d")


async def log_habit(text: str) -> dict:
    name = await normalize_habit_name(text)
    habit = await find_habit_by_name(name)
    habit_id = habit["id"] if habit else await create_habit(name)

    today = _today_str()
    newly = await _log_habit_row(habit_id, today, datetime.now(TZ).isoformat())
    streak = await compute_streak(habit_id)

    return {"habit": habit["name"] if habit else name, "habit_id": habit_id,
            "newly_logged": newly, "streak": streak}


async def compute_streak(habit_id: int) -> int:
    """Consecutive logged days ending today (or yesterday, if today isn't logged yet)."""
    dates = set(await get_habit_logs(habit_id, limit=365))
    if not dates:
        return 0

    today = datetime.now(TZ).date()
    cursor = today if today.strftime("%Y-%m-%d") in dates else today - timedelta(days=1)

    streak = 0
    while cursor.strftime("%Y-%m-%d") in dates:
        streak += 1
        cursor -= timedelta(days=1)
    return streak


async def get_habit_summary() -> list[dict]:
    """All active habits with current streak + whether logged today, for digest display."""
    habits = await get_all_habits()
    today = _today_str()

    summary = []
    for h in habits:
        dates = await get_habit_logs(h["id"], limit=365)
        summary.append({
            "name": h["name"],
            "streak": await compute_streak(h["id"]),
            "logged_today": today in dates,
        })
    return summary
