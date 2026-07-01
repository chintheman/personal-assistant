"""
Morning briefing builder.
Pulls today's calendar events and formats a clean agenda.
Returns None if no events today — bot should NOT send anything in that case.
"""

import os
from datetime import datetime
from zoneinfo import ZoneInfo

from core.calendar_ops import get_events_for_day, detect_conflicts
from core.db import get_due_todos

TZ = ZoneInfo(os.getenv("PA_TIMEZONE", "Asia/Singapore"))


async def build_morning_briefing() -> dict | None:
    """
    Returns briefing dict or None if no events AND no due/overdue todos today.
    Caller must handle the None → no push case.
    """
    today = datetime.now(TZ)
    events = get_events_for_day(today)
    end_of_day = today.replace(hour=23, minute=59, second=59, microsecond=0)
    due_todos = await get_due_todos(end_of_day.isoformat())

    if not events and not due_todos:
        return None  # Nothing due, nothing scheduled → no briefing, no noise

    conflicts = detect_conflicts(events)

    return {
        "date": today.strftime("%A, %d %b %Y"),
        "events": events,
        "conflicts": conflicts,
        "event_count": len(events),
        "due_todos": due_todos,
    }
