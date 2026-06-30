"""
Telegram bot message handlers.
This is the interface layer — thin, no business logic.
Routing → classification in core/llm.py
Action execution in core/*
"""

import re
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
import os

from telegram import Update
from telegram.ext import ContextTypes

from core.llm import classify_message, parse_calendar_intent
from core.ideas import capture_idea
from core.links import capture_link
from core.calendar_handler import handle_calendar_intent
from core.digest import build_digest
from core.briefing import build_morning_briefing
from core.db import (
    archive_idea, archive_link, mark_link_read, snooze_item,
    search_ideas, search_links,
)
from bot.formatters import (
    fmt_idea_captured, fmt_link_captured, fmt_digest,
    fmt_briefing, fmt_ideas_search, fmt_links_search,
)

TZ = ZoneInfo(os.getenv("PA_TIMEZONE", "Asia/Singapore"))


# ─── TRIAGE COMMAND PARSER ─────────────────────────────────────────────────────

_SNOOZE_DURATION = re.compile(r"(\d+)(d|h|w)", re.I)


def _parse_snooze_duration(text: str) -> timedelta:
    m = _SNOOZE_DURATION.search(text)
    if not m:
        return timedelta(days=1)
    n, unit = int(m.group(1)), m.group(2).lower()
    if unit == "h":
        return timedelta(hours=n)
    if unit == "w":
        return timedelta(weeks=n)
    return timedelta(days=n)


def _parse_triage(text: str) -> dict | None:
    """
    Detect text commands:
      archive i<id>  |  archive l<id>
      read l<id>
      snooze i<id> 7d  |  snooze l<id> 3h
    Returns parsed dict or None if not a triage command.
    """
    t = text.strip().lower()
    m = re.match(r"^(archive|read|snooze)\s+([il])(\d+)(.*)$", t)
    if not m:
        return None
    action = m.group(1)
    kind = "idea" if m.group(2) == "i" else "link"
    item_id = int(m.group(3))
    rest = m.group(4).strip()
    duration = _parse_snooze_duration(rest) if action == "snooze" else None
    return {"action": action, "kind": kind, "item_id": item_id, "duration": duration}


def _parse_query(text: str) -> dict | None:
    """
    Detect on-demand queries:
      show ideas [about X]
      show links [about X]
      digest / backlog
    """
    t = text.strip().lower()
    if re.search(r"\b(digest|backlog|what.*plate|queue)\b", t):
        return {"type": "digest"}
    m = re.search(r"\bshow\s+(ideas?|links?)\b(?:\s+(?:about|on|for)\s+(.+))?", t)
    if m:
        kind = "idea" if m.group(1).startswith("idea") else "link"
        query = m.group(2) or ""
        return {"type": kind, "query": query}
    if re.search(r"\bbrief(ing)?\b", t):
        return {"type": "briefing"}
    return None


# ─── MAIN MESSAGE HANDLER ──────────────────────────────────────────────────────

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text or ""
    if not text:
        return

    # 1. Check triage commands first (synchronous parse — no LLM needed)
    triage = _parse_triage(text)
    if triage:
        await _handle_triage(update, triage)
        return

    # 2. Check on-demand queries (synchronous parse)
    query_intent = _parse_query(text)
    if query_intent:
        await _handle_query(update, query_intent)
        return

    # 3. Route via LLM classifier
    classification = await classify_message(text)
    intent = classification.get("intent", "idea")
    url = classification.get("url")

    if intent == "link" and url:
        await update.message.reply_text("🔗 Fetching and summarizing…")
        result = await capture_link(url)
        await update.message.reply_text(fmt_link_captured(result), parse_mode="HTML")

    elif intent == "calendar":
        now_iso = datetime.now(TZ).isoformat()
        cal_intent = await parse_calendar_intent(text, now_iso)
        response = await handle_calendar_intent(cal_intent)
        await update.message.reply_text(response, parse_mode="HTML")

    else:
        # idea
        result = await capture_idea(text)
        await update.message.reply_text(fmt_idea_captured(result), parse_mode="HTML")


# ─── TRIAGE ─────────────────────────────────────────────────────────────────────

async def _handle_triage(update: Update, triage: dict):
    action = triage["action"]
    kind = triage["kind"]
    item_id = triage["item_id"]

    if action == "archive":
        if kind == "idea":
            await archive_idea(item_id)
        else:
            await archive_link(item_id)
        await update.message.reply_text(f"✅ {kind.capitalize()} #{item_id} archived.")

    elif action == "read":
        if kind == "link":
            await mark_link_read(item_id)
            await update.message.reply_text(f"✅ Link #{item_id} marked as read.")
        else:
            await update.message.reply_text("ℹ️ 'read' only applies to links (l<id>).")

    elif action == "snooze":
        wake_at = datetime.now(TZ) + triage["duration"]
        await snooze_item(kind, item_id, wake_at)
        wake_str = wake_at.strftime("%d %b at %I:%M %p")
        await update.message.reply_text(f"⏰ {kind.capitalize()} #{item_id} snoozed until {wake_str}.")


# ─── ON-DEMAND QUERIES ──────────────────────────────────────────────────────────

async def _handle_query(update: Update, query_intent: dict):
    qtype = query_intent["type"]

    if qtype == "digest":
        digest = await build_digest()
        await update.message.reply_text(fmt_digest(digest), parse_mode="HTML")

    elif qtype == "briefing":
        briefing = build_morning_briefing()
        if not briefing:
            await update.message.reply_text("📅 Nothing on your calendar today.")
        else:
            await update.message.reply_text(fmt_briefing(briefing), parse_mode="HTML")

    elif qtype == "idea":
        ideas = await search_ideas(query_intent.get("query", ""))
        await update.message.reply_text(
            fmt_ideas_search(ideas, query_intent.get("query", "all")), parse_mode="HTML"
        )

    elif qtype == "link":
        links = await search_links(query_intent.get("query", ""))
        await update.message.reply_text(
            fmt_links_search(links, query_intent.get("query", "all")), parse_mode="HTML"
        )


# ─── COMMAND HANDLERS ──────────────────────────────────────────────────────────

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 <b>Personal Assistant online.</b>\n\n"
        "Send me anything:\n"
        "• A thought or idea → captured + tagged\n"
        "• A URL → fetched, summarized, saved\n"
        "• A calendar command → 'what's on today', 'create meeting Friday 2pm'\n\n"
        "Commands:\n"
        "• <code>digest</code> — see your backlog\n"
        "• <code>archive i3</code> — archive idea #3\n"
        "• <code>archive l7</code> — archive link #7\n"
        "• <code>read l7</code> — mark link #7 read\n"
        "• <code>snooze i3 7d</code> — snooze idea #3 for 7 days\n"
        "• <code>show ideas about AI</code> — search ideas\n"
        "• <code>show links about design</code> — search links",
        parse_mode="HTML",
    )


async def cmd_digest(update: Update, context: ContextTypes.DEFAULT_TYPE):
    digest = await build_digest()
    await update.message.reply_text(fmt_digest(digest), parse_mode="HTML")


async def cmd_briefing(update: Update, context: ContextTypes.DEFAULT_TYPE):
    briefing = build_morning_briefing()
    if not briefing:
        await update.message.reply_text("📅 Nothing on your calendar today.")
    else:
        await update.message.reply_text(fmt_briefing(briefing), parse_mode="HTML")
