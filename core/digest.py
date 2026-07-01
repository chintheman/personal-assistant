"""
Daily digest builder.
Phase 1: basic version — no decay logic, but items ARE marked shown so
the same list doesn't dump verbatim every day. Decay/prioritization in Phase 2.
"""

from datetime import datetime
from core.db import (
    get_active_ideas, get_active_links, get_open_todos,
    mark_idea_shown, mark_link_shown, log_digest_item,
)
from core.habits import get_habit_summary

MAX_IDEAS = 5
MAX_LINKS = 5
MAX_TODOS = 8


async def build_digest() -> dict:
    """
    Returns a digest dict with todos + ideas + links + habit streaks to surface today.
    Also marks ideas/links as shown so tomorrow's list isn't identical.
    Todos always show in full (they're actionable, not backlog) until done/deleted.
    """
    ideas = await get_active_ideas(limit=MAX_IDEAS)
    links = await get_active_links(limit=MAX_LINKS)
    todos = await get_open_todos(limit=MAX_TODOS)
    habits = await get_habit_summary()

    # Mark shown so we don't re-dump verbatim tomorrow
    for idea in ideas:
        await mark_idea_shown(idea["id"])
        await log_digest_item("idea", idea["id"], "shown")
    for link in links:
        await mark_link_shown(link["id"])
        await log_digest_item("link", link["id"], "shown")

    return {
        "ideas": ideas,
        "links": links,
        "todos": todos,
        "habits": habits,
        "generated_at": datetime.utcnow().isoformat(),
        "has_content": bool(ideas or links or todos),
    }
