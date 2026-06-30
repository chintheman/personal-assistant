"""
Links capture pipeline.
Capture → Fetch → Summarize → Categorize → Store.
"""

import httpx
from bs4 import BeautifulSoup

from core.db import insert_link
from core.llm import categorize, summarize_url_content

FETCH_TIMEOUT = 10
MAX_BODY_CHARS = 4000


async def _fetch_page(url: str) -> tuple[str, str]:
    """Returns (title, body_text). Gracefully degrades on failure."""
    try:
        async with httpx.AsyncClient(follow_redirects=True, timeout=FETCH_TIMEOUT) as client:
            resp = await client.get(url, headers={"User-Agent": "Mozilla/5.0 (PA/1.0)"})
            resp.raise_for_status()
            soup = BeautifulSoup(resp.text, "html.parser")
            title = soup.title.string.strip() if soup.title else url
            # Extract readable text: remove scripts/styles
            for tag in soup(["script", "style", "nav", "footer", "header"]):
                tag.decompose()
            body = " ".join(soup.get_text(separator=" ").split())
            return title, body[:MAX_BODY_CHARS]
    except Exception as e:
        return url, f"[Could not fetch page: {e}]"


async def capture_link(url: str) -> dict:
    """Full link capture pipeline. Returns stored record metadata."""
    title, body = await _fetch_page(url)
    summary = await summarize_url_content(body)
    tag = await categorize(f"{title} {summary}")
    link_id = await insert_link(url=url, title=title, summary=summary, tags=tag)
    return {
        "id": link_id,
        "title": title,
        "summary": summary,
        "tag": tag,
    }
