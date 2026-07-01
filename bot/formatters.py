"""
Message formatters — convert core data structures into Telegram-ready HTML strings.
No business logic here. Only presentation.
"""

from datetime import datetime
import os
from zoneinfo import ZoneInfo

TZ = ZoneInfo(os.getenv("PA_TIMEZONE", "Asia/Singapore"))


def _local_time(iso: str) -> str:
    try:
        return datetime.fromisoformat(iso).astimezone(TZ).strftime("%I:%M %p")
    except Exception:
        return iso


def _local_date(iso: str) -> str:
    try:
        return datetime.fromisoformat(iso).astimezone(TZ).strftime("%a %d %b")
    except Exception:
        return iso


def fmt_briefing(briefing: dict) -> str:
    lines = [f"☀️ <b>Good morning! Here's your {briefing['date']} agenda:</b>\n"]
    for ev in briefing["events"]:
        start = _local_time(ev["start"])
        end = _local_time(ev["end"])
        loc = f" · 📍{ev['location']}" if ev.get("location") else ""
        lines.append(f"• <b>{ev['title']}</b> {start}–{end}{loc}")

    if briefing["conflicts"]:
        lines.append("\n⚠️ <b>Conflicts detected:</b>")
        for a, b in briefing["conflicts"]:
            lines.append(f"  ↔ {a['title']} ↔ {b['title']}")

    due_todos = briefing.get("due_todos") or []
    if due_todos:
        lines.append("\n✅ <b>Due today / overdue:</b>")
        for t in due_todos:
            lines.append(f"  <code>#{t['id']}</code> [{t.get('priority', 'medium')}] {t['text']}")

    lines.append(f"\n{briefing['event_count']} event{'s' if briefing['event_count'] != 1 else ''} today. Have a great one! 🚀")
    return "\n".join(lines)


def fmt_idea_captured(result: dict) -> str:
    summary = result.get("summary", "")
    return (
        f"💡 Captured · <code>#{result['id']}</code> · <b>{result['tag']}</b>\n"
        f"{summary}"
    )


def fmt_link_captured(result: dict) -> str:
    return (
        f"🔗 Saved · <code>#{result['id']}</code> · <b>{result['tag']}</b>\n"
        f"<b>{result['title']}</b>\n"
        f"{result['summary']}"
    )


def fmt_digest(digest: dict) -> str:
    if not digest["has_content"]:
        return "✨ Backlog clear — nothing queued. Keep capturing!"

    lines = ["📬 <b>Daily Digest</b>\n"]

    if digest.get("todos"):
        lines.append("✅ <b>Todos</b>")
        for t in digest["todos"]:
            due = f" · due {_local_date(t['due_at'])}" if t.get("due_at") else ""
            lines.append(f"  <code>#{t['id']}</code> [{t.get('priority', 'medium')}]{due} {t['text']}")

    if digest["ideas"]:
        lines.append("\n💡 <b>Ideas</b>")
        for idea in digest["ideas"]:
            display = idea.get("summary") or idea["text"][:80]
            tags = f"[{idea['tags']}]" if idea.get("tags") else ""
            lines.append(f"  <code>#{idea['id']}</code> {tags} {display}")

    if digest["links"]:
        lines.append("\n🔗 <b>Links</b>")
        for link in digest["links"]:
            tags = f"[{link['tags']}]" if link.get("tags") else ""
            lines.append(f"  <code>#{link['id']}</code> {tags} <b>{link.get('title', link['url'])}</b>")
            if link.get("summary"):
                lines.append(f"    {link['summary']}")

    if digest.get("habits"):
        lines.append("\n📊 <b>Habits</b>")
        for h in digest["habits"]:
            mark = "✅" if h["logged_today"] else "⬜"
            lines.append(f"  {mark} {h['name']} — {h['streak']} day streak")

    lines.append(
        "\n<i>Just reply naturally — \"complete todo 3\", \"delete idea 3\", \"snooze link 7 for a week\", \"mark link 2 read\"</i>"
    )
    return "\n".join(lines)


def fmt_ideas_search(ideas: list[dict], query: str) -> str:
    if not ideas:
        return f"🔍 No ideas found matching <i>{query}</i>"
    lines = [f"🔍 Ideas matching <i>{query}</i>:\n"]
    for idea in ideas:
        display = idea.get("summary") or idea["text"][:80]
        lines.append(f"• <code>#{idea['id']}</code> [{idea.get('tags', '')}] {display}")
    return "\n".join(lines)


def fmt_links_search(links: list[dict], query: str) -> str:
    if not links:
        return f"🔍 No links found matching <i>{query}</i>"
    lines = [f"🔍 Links matching <i>{query}</i>:\n"]
    for link in links:
        lines.append(
            f"• <code>#{link['id']}</code> [{link.get('tags', '')}] "
            f"<b>{link.get('title', link['url'])}</b>"
        )
    return "\n".join(lines)
