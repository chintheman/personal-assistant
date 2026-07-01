"""
Model-agnostic LLM wrapper using LiteLLM.
Swap the model by setting PA_LLM_MODEL env var — no code changes needed.
"""

import os
import json
import asyncio
from litellm import acompletion

MODEL = os.getenv("PA_LLM_MODEL", "claude-haiku-3-5")

CANONICAL_TAGS = [
    "tech", "productivity", "finance", "health", "learning",
    "creative", "personal", "crypto", "career", "misc",
]


async def _chat(system: str, user: str, max_tokens: int = 400) -> str:
    resp = await acompletion(
        model=MODEL,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        max_tokens=max_tokens,
        temperature=0.2,
    )
    return resp.choices[0].message.content.strip()


# ─── ROUTING ───────────────────────────────────────────────────────────────────

ROUTE_SYSTEM = """
You are the intent router for a personal assistant.
Classify the user message into exactly one of:
  calendar  — mentions dates, times, events, scheduling, meetings, "what's on", "move", "reschedule", "free slot"
  link      — message contains a URL (http/https)
  idea      — anything else (free-form thought, question, note)

Also extract the URL if present.

Respond with JSON only:
{"intent": "calendar"|"link"|"idea", "url": "<url or null>"}
""".strip()


async def classify_message(text: str) -> dict:
    """Returns {'intent': str, 'url': str|None}"""
    raw = await _chat(ROUTE_SYSTEM, text, max_tokens=60)
    try:
        return json.loads(raw)
    except Exception:
        # Fallback: detect URL manually
        import re
        urls = re.findall(r"https?://\S+", text)
        if urls:
            return {"intent": "link", "url": urls[0]}
        return {"intent": "idea", "url": None}


# ─── CATEGORIZATION ────────────────────────────────────────────────────────────

CATEGORIZE_SYSTEM = f"""
You are a categorization engine for a personal assistant.
Assign ONE tag from the canonical list below, or invent a short lowercase slug if none fit.
Canonical tags: {', '.join(CANONICAL_TAGS)}

Respond with JSON only: {{"tag": "<tag>"}}
""".strip()


async def categorize(text: str) -> str:
    raw = await _chat(CATEGORIZE_SYSTEM, text[:500], max_tokens=30)
    try:
        return json.loads(raw)["tag"]
    except Exception:
        return "misc"


# ─── SUMMARIZATION ─────────────────────────────────────────────────────────────

SUMMARIZE_SYSTEM = """
You are a summarization engine. Produce a single plain-English sentence (max 20 words) that captures the core idea.
Respond with the sentence only — no quotes, no prefix.
""".strip()


async def summarize_text(text: str, max_chars: int = 2000) -> str:
    return await _chat(SUMMARIZE_SYSTEM, text[:max_chars], max_tokens=60)


SUMMARIZE_URL_SYSTEM = """
You are given the text content of a web page.
Produce a 2-3 sentence plain-English summary focused on what the page is actually about.
No prefixes, no quotes.
""".strip()


async def summarize_url_content(content: str) -> str:
    return await _chat(SUMMARIZE_URL_SYSTEM, content[:3000], max_tokens=150)


# ─── TODO PRIORITY ─────────────────────────────────────────────────────────────

PRIORITY_SYSTEM = """
You are a priority classifier for a personal to-do list.
Assign exactly one priority based on urgency/importance language and any deadline mentioned: high, medium, or low.
Default to medium if unclear.

Respond with JSON only: {"priority": "high"|"medium"|"low"}
""".strip()


async def infer_priority(text: str) -> str:
    raw = await _chat(PRIORITY_SYSTEM, text[:500], max_tokens=20)
    try:
        p = json.loads(raw)["priority"]
        return p if p in ("high", "medium", "low") else "medium"
    except Exception:
        return "medium"


# ─── HABITS ─────────────────────────────────────────────────────────────────────

HABIT_NAME_SYSTEM = """
You normalize a freeform message into a short habit name (2-4 words, lowercase, no punctuation) for a habit tracker.
Examples: "I finally did my workout today" -> "workout", "read for 20 min before bed" -> "reading", "meditated this morning" -> "meditation".

Respond with JSON only: {"habit": "<name>"}
""".strip()


async def normalize_habit_name(text: str) -> str:
    raw = await _chat(HABIT_NAME_SYSTEM, text[:300], max_tokens=20)
    try:
        return json.loads(raw)["habit"].strip().lower()
    except Exception:
        return text[:30].strip().lower()


# ─── EMAIL TRIAGE ───────────────────────────────────────────────────────────────

EMAIL_TRIAGE_SYSTEM = """
You triage an email inbox for a personal assistant. You are given a numbered list of emails
(sender, subject, snippet). For each one, decide if it genuinely needs the user's action
(reply, decision, payment, deadline) versus FYI/noise (newsletter, notification, receipt).
Write a one-line plain-English summary for each.

Respond with JSON only:
{"items": [{"index": 0, "action_needed": true|false, "summary": "<one line>"}]}
""".strip()


async def triage_emails(emails_text: str) -> list[dict]:
    raw = await _chat(EMAIL_TRIAGE_SYSTEM, emails_text[:4000], max_tokens=600)
    try:
        return json.loads(raw)["items"]
    except Exception:
        return []


# ─── CALENDAR NLU ──────────────────────────────────────────────────────────────

CALENDAR_SYSTEM = """
You are a Google Calendar NLU engine. Extract a structured calendar intent from the user message.

Supported operations: create, update, delete, query, find_free_slot

For create: extract title, start_datetime (ISO8601), end_datetime (ISO8601), description (optional)
For update: extract event_reference (natural language title/time), and any field changes
For delete: extract event_reference
For query: extract timeframe (e.g. "today", "tomorrow", "this week", "next Monday")
For find_free_slot: extract duration_minutes, timeframe, and optional constraints

Current date/time context will be injected by the caller.

Respond with JSON only:
{
  "operation": "create|update|delete|query|find_free_slot",
  "title": null,
  "start_datetime": null,
  "end_datetime": null,
  "description": null,
  "event_reference": null,
  "changes": {},
  "timeframe": null,
  "duration_minutes": null
}
""".strip()


async def parse_calendar_intent(text: str, now_iso: str) -> dict:
    context = f"Current date/time: {now_iso}\n\nUser message: {text}"
    raw = await _chat(CALENDAR_SYSTEM, context, max_tokens=300)
    try:
        return json.loads(raw)
    except Exception:
        return {"operation": "query", "timeframe": "today"}


# ─── URGENCY CHECK ─────────────────────────────────────────────────────────────

URGENCY_SYSTEM = """
You are an urgency classifier for a personal assistant notification system.
Assess whether an event/situation is genuinely time-sensitive and warrants an immediate interrupt.

Conservative threshold: only things that require action in the next 2-4 hours OR will cause a real problem if not addressed immediately.

Examples of urgent: calendar conflict in the next 2 hours, event starting in 30 minutes with no prep noted
Examples of NOT urgent: general news, new idea, a link to read later, a meeting 3 days away

Respond with JSON only: {"urgent": true|false, "reason": "<one sentence>"}
""".strip()


async def assess_urgency(situation: str) -> dict:
    raw = await _chat(URGENCY_SYSTEM, situation, max_tokens=80)
    try:
        return json.loads(raw)
    except Exception:
        return {"urgent": False, "reason": "Could not assess urgency"}
