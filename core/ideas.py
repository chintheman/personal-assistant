"""
Ideas capture pipeline.
Capture → Categorize → Summarize (if long) → Store.
"""

from core.db import insert_idea
from core.llm import categorize, summarize_text

SUMMARY_THRESHOLD = 80  # chars — summarize if longer than this


async def capture_idea(text: str) -> dict:
    """Full capture pipeline. Returns the stored record metadata."""
    tag = await categorize(text)
    summary = None
    if len(text) > SUMMARY_THRESHOLD:
        summary = await summarize_text(text)

    idea_id = await insert_idea(text=text, summary=summary, tags=tag)
    return {
        "id": idea_id,
        "tag": tag,
        "summary": summary or text[:80],
    }
