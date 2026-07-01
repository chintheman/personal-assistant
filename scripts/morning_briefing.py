#!/usr/bin/env python3
"""
Morning briefing cron script.
Run daily at configured time (default 08:00 SGT).
Sends the day's agenda IF there are events. Silent if no events.
"""

import asyncio
import os
import sys
from pathlib import Path

# Resolve project root regardless of cwd
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from dotenv import load_dotenv
load_dotenv(PROJECT_ROOT / ".env")

from core.briefing import build_morning_briefing
from core.alerts import send_alert
from bot.formatters import fmt_briefing


async def run():
    briefing = await build_morning_briefing()

    if not briefing:
        # No events today — stay silent as spec'd
        print("[briefing] No events today — skipping push.")
        return

    message = fmt_briefing(briefing)
    await send_alert(message)
    print(f"[briefing] Sent briefing: {briefing['event_count']} events on {briefing['date']}")


if __name__ == "__main__":
    asyncio.run(run())
