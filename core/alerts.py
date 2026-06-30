"""
Alert path — out-of-band Telegram notifications.
Wired in from Day 1 so we're never retrofitting interrupt logic.
All business logic that decides WHAT is urgent lives here.
The bot handler that routes incoming messages is a separate concern.
"""

import os
import asyncio
import httpx

BOT_TOKEN = os.getenv("PA_BOT_TOKEN", "")
CHAT_ID = os.getenv("PA_CHAT_ID", "")
TELEGRAM_API = f"https://api.telegram.org/bot{BOT_TOKEN}"


async def send_alert(text: str, parse_mode: str = "HTML"):
    """Fire-and-forget alert to the configured chat. Safe to call from any async context."""
    if not BOT_TOKEN or not CHAT_ID:
        print(f"[ALERT] (bot not configured) {text}")
        return
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            await client.post(
                f"{TELEGRAM_API}/sendMessage",
                json={"chat_id": CHAT_ID, "text": text, "parse_mode": parse_mode},
            )
    except Exception as e:
        print(f"[ALERT SEND FAILED] {e} — message: {text}")


async def alert_calendar_conflict(event_a: dict, event_b: dict):
    """Immediate alert on detected calendar conflict."""
    msg = (
        "⚠️ <b>Calendar conflict detected</b>\n\n"
        f"• <b>{event_a['title']}</b> ({event_a['start']})\n"
        f"• <b>{event_b['title']}</b> ({event_b['start']})\n\n"
        "These two events overlap. Tap reply to reschedule."
    )
    await send_alert(msg)


async def alert_upcoming_event(event: dict, minutes_until: int):
    """Nudge for an event happening soon."""
    msg = (
        f"🔔 <b>{event['title']}</b> in {minutes_until} min\n"
        f"{'📍 ' + event['location'] if event.get('location') else ''}"
    )
    await send_alert(msg.strip())
