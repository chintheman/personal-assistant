"""
Morning briefing builder.
Pulls today's calendar events and formats a clean agenda.
Returns None if no events today — bot should NOT send anything in that case.
"""

import os
from datetime import datetime
from zoneinfo import ZoneInfo

from core.calendar_ops import get_events_for_day, detect_conflicts

TZ = ZoneInfo(os.getenv("PA_TIMEZONE", "Asia/Singapore"))


def build_morning_briefing() -> dict | None:
    """
    Returns briefing dict or None if no events today.
    Caller must handle the None → no push case.
    """
    today = datetime.now(TZ)
    events = get_events_for_day(today)

    if not events:
        return None  # No events → no briefing, no noise

    conflicts = detect_conflicts(events)

    return {
        "date": today.strftime("%A, %d %b %Y"),
        "events": events,
        "conflicts": conflicts,
        "event_count": len(events),
    }
