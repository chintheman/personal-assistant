"""
Daily digest builder.
Phase 1: basic version — no decay logic, but items ARE marked shown so
the same list doesn't dump verbatim every day. Decay/prioritization in Phase 2.
"""

from datetime import datetime
from core.db import (
    get_active_ideas, get_active_links,
    mark_idea_shown, mark_link_shown, log_digest_item,
)

MAX_IDEAS = 5
MAX_LINKS = 5


async def build_digest() -> dict:
    """
    Returns a digest dict with ideas + links to surface today.
    Also marks each item as shown so tomorrow's list isn't identical.
    """
    ideas = await get_active_ideas(limit=MAX_IDEAS)
    links = await get_active_links(limit=MAX_LINKS)

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
        "generated_at": datetime.utcnow().isoformat(),
        "has_content": bool(ideas or links),
    }
