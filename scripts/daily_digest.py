#!/usr/bin/env python3
"""
Daily digest cron script.
Run daily at configured time (default 20:00 SGT).
Sends backlog digest if there's content. Silent if backlog is empty.
"""

import asyncio
import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from dotenv import load_dotenv
load_dotenv(PROJECT_ROOT / ".env")

from core.digest import build_digest
from core.alerts import send_alert
from bot.formatters import fmt_digest


async def run():
    digest = await build_digest()

    if not digest["has_content"]:
        print("[digest] Nothing in backlog — skipping push.")
        return

    message = fmt_digest(digest)
    await send_alert(message)
    idea_count = len(digest["ideas"])
    link_count = len(digest["links"])
    print(f"[digest] Sent digest: {idea_count} ideas, {link_count} links.")


if __name__ == "__main__":
    asyncio.run(run())
