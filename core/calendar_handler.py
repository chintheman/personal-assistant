"""
Calendar command handler.
Takes a parsed intent from llm.parse_calendar_intent() and executes it.
Returns a human-readable response string.
"""

import os
from datetime import datetime
from zoneinfo import ZoneInfo

from core import calendar_ops
from core.alerts import alert_calendar_conflict

TZ = ZoneInfo(os.getenv("PA_TIMEZONE", "Asia/Singapore"))


def _fmt_event(ev: dict) -> str:
    try:
        dt = datetime.fromisoformat(ev["start"]).astimezone(TZ)
        time_str = dt.strftime("%a %d %b, %I:%M %p")
    except Exception:
        time_str = ev["start"]
    loc = f"\n📍 {ev['location']}" if ev.get("location") else ""
    return f"• <b>{ev['title']}</b> — {time_str}{loc}"


def _fmt_slot(slot: dict) -> str:
    try:
        start = datetime.fromisoformat(slot["start"]).astimezone(TZ)
        return start.strftime("%a %d %b, %I:%M %p")
    except Exception:
        return slot["start"]


async def handle_calendar_intent(intent: dict) -> str:
    op = intent.get("operation", "query")

    if op == "query":
        timeframe = intent.get("timeframe", "today")
        from datetime import timedelta
        now = datetime.now(TZ)
        if "tomorrow" in timeframe:
            target = now + timedelta(days=1)
        elif "week" in timeframe:
            # Return next 7 days
            events = calendar_ops.get_events_in_range(now, now + timedelta(days=7))
            if not events:
                return "📅 Nothing on your calendar this week."
            lines = [f"📅 <b>Next 7 days:</b>"] + [_fmt_event(e) for e in events]
            return "\n".join(lines)
        else:
            target = now

        events = calendar_ops.get_events_for_day(target)
        label = "Today" if target.date() == now.date() else target.strftime("%A, %d %b")
        if not events:
            return f"📅 Nothing on your calendar {label.lower()}."
        lines = [f"📅 <b>{label}:</b>"] + [_fmt_event(e) for e in events]
        return "\n".join(lines)

    elif op == "create":
        title = intent.get("title") or "New Event"
        start = intent.get("start_datetime")
        end = intent.get("end_datetime")
        if not start or not end:
            return "❌ I need a start and end time to create an event. Try: 'Create lunch with Alex tomorrow 1pm–2pm'"
        desc = intent.get("description") or ""
        ev = calendar_ops.create_event(title=title, start=start, end=end, description=desc)
        # Check for conflicts on that day
        day_events = calendar_ops.get_events_for_day(datetime.fromisoformat(start).astimezone(TZ))
        conflicts = calendar_ops.detect_conflicts(day_events)
        response = f"✅ Created: <b>{ev['title']}</b> — {_fmt_event(ev)}"
        if conflicts:
            import asyncio
            for a, b in conflicts:
                asyncio.create_task(alert_calendar_conflict(a, b))
            response += "\n\n⚠️ Conflict detected with existing events — check your calendar."
        return response

    elif op == "update":
        ref = intent.get("event_reference", "")
        ev = calendar_ops.find_event_by_reference(ref)
        if not ev:
            return f"❌ Couldn't find an event matching '{ref}' in the next 7 days."
        changes = intent.get("changes") or {}
        # Flatten simple fields from intent
        for field in ["start_datetime", "end_datetime", "title"]:
            if intent.get(field):
                key = field.replace("_datetime", "")
                changes[key] = intent[field]
        updated = calendar_ops.update_event(ev["id"], changes)
        return f"✅ Updated: {_fmt_event(updated)}"

    elif op == "delete":
        ref = intent.get("event_reference", "")
        ev = calendar_ops.find_event_by_reference(ref)
        if not ev:
            return f"❌ Couldn't find '{ref}' in the next 7 days."
        ok = calendar_ops.delete_event(ev["id"])
        return f"🗑️ Deleted: <b>{ev['title']}</b>" if ok else "❌ Delete failed — check Calendar."

    elif op == "find_free_slot":
        dur = intent.get("duration_minutes") or 60
        slots = calendar_ops.find_free_slots(duration_minutes=dur)
        if not slots:
            return f"😬 No free {dur}-minute slots found in the next 7 days."
        lines = [f"🕐 Free {dur}-min slots:"] + [f"• {_fmt_slot(s)}" for s in slots]
        return "\n".join(lines)

    return "🤔 I'm not sure what you want to do with the calendar. Try: 'what's on today', 'create meeting tomorrow at 3pm', or 'find free 2-hour block this week'."
