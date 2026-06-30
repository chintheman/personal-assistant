"""
Agent loop — the brain of the personal assistant.

Every inbound message goes through run_agent_turn():
  1. Load conversation history for this chat
  2. Feed to LLM with full tool definitions
  3. Execute tool calls in a loop until the model gives a final text reply
  4. Save history + return the reply

No business logic lives in the bot layer — only here.
"""

import os
import json
import asyncio
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from litellm import acompletion

from core.conversation import get_history, append_message, clear_old_history
from core.db import (
    insert_idea, get_active_ideas, archive_idea, mark_idea_shown, search_ideas,
    insert_link, get_active_links, archive_link, mark_link_read, search_links,
    snooze_item, log_digest_item,
)
from core.links import capture_link as _capture_link_pipeline
from core.ideas import capture_idea as _capture_idea_pipeline

MODEL = os.getenv("PA_LLM_MODEL", "deepseek/deepseek-chat")
TZ = ZoneInfo(os.getenv("PA_TIMEZONE", "Asia/Singapore"))

# ─── TOOL DEFINITIONS ──────────────────────────────────────────────────────────
# These are what the LLM sees and can call.

TOOLS = [
    # ── Calendar ──────────────────────────────────────────────────────────────
    {
        "type": "function",
        "function": {
            "name": "calendar_query",
            "description": "Read calendar events. Use for 'what's on today/tomorrow/this week', 'show my schedule', any query about existing events.",
            "parameters": {
                "type": "object",
                "properties": {
                    "timeframe": {
                        "type": "string",
                        "description": "Natural language timeframe: 'today', 'tomorrow', 'this week', 'next Monday', or an ISO date string YYYY-MM-DD."
                    }
                },
                "required": ["timeframe"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "calendar_create",
            "description": "Create a new calendar event.",
            "parameters": {
                "type": "object",
                "properties": {
                    "title": {"type": "string"},
                    "start_datetime": {"type": "string", "description": "ISO8601 datetime string"},
                    "end_datetime": {"type": "string", "description": "ISO8601 datetime string"},
                    "description": {"type": "string", "default": ""}
                },
                "required": ["title", "start_datetime", "end_datetime"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "calendar_update",
            "description": "Update an existing calendar event by its title reference.",
            "parameters": {
                "type": "object",
                "properties": {
                    "event_reference": {"type": "string", "description": "Title fragment to find the event"},
                    "changes": {
                        "type": "object",
                        "description": "Fields to update: title, start (ISO8601), end (ISO8601), description"
                    }
                },
                "required": ["event_reference", "changes"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "calendar_delete",
            "description": "Delete a calendar event by title reference.",
            "parameters": {
                "type": "object",
                "properties": {
                    "event_reference": {"type": "string"}
                },
                "required": ["event_reference"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "calendar_find_free_slots",
            "description": "Find open time slots of a given duration in the next N days.",
            "parameters": {
                "type": "object",
                "properties": {
                    "duration_minutes": {"type": "integer"},
                    "within_days": {"type": "integer", "default": 7}
                },
                "required": ["duration_minutes"]
            }
        }
    },
    # ── Ideas ─────────────────────────────────────────────────────────────────
    {
        "type": "function",
        "function": {
            "name": "idea_capture",
            "description": "Capture a new idea/note/thought. Runs full pipeline: categorize, summarize if long, store.",
            "parameters": {
                "type": "object",
                "properties": {
                    "text": {"type": "string", "description": "The idea text to capture"}
                },
                "required": ["text"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "idea_delete",
            "description": "Permanently archive/delete an idea by its numeric ID.",
            "parameters": {
                "type": "object",
                "properties": {
                    "idea_id": {"type": "integer"}
                },
                "required": ["idea_id"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "idea_query",
            "description": "Search or list ideas. Use for 'show my ideas', 'ideas about X', 'what ideas do I have on Y'.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Search keywords, or empty string for all active ideas"},
                    "limit": {"type": "integer", "default": 10}
                },
                "required": ["query"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "idea_snooze",
            "description": "Snooze an idea so it won't appear in digests until a future date.",
            "parameters": {
                "type": "object",
                "properties": {
                    "idea_id": {"type": "integer"},
                    "snooze_until": {"type": "string", "description": "ISO8601 datetime or natural language like '1 week', '3 days', '2 hours'"}
                },
                "required": ["idea_id", "snooze_until"]
            }
        }
    },
    # ── Links ─────────────────────────────────────────────────────────────────
    {
        "type": "function",
        "function": {
            "name": "link_capture",
            "description": "Capture a URL: fetch, summarize, categorize and store. Use when user sends a URL.",
            "parameters": {
                "type": "object",
                "properties": {
                    "url": {"type": "string"}
                },
                "required": ["url"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "link_delete",
            "description": "Archive/delete a saved link by its numeric ID.",
            "parameters": {
                "type": "object",
                "properties": {
                    "link_id": {"type": "integer"}
                },
                "required": ["link_id"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "link_mark_read",
            "description": "Mark a link as read so it no longer appears in digests.",
            "parameters": {
                "type": "object",
                "properties": {
                    "link_id": {"type": "integer"}
                },
                "required": ["link_id"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "link_query",
            "description": "Search or list saved links. Use for 'show my links', 'links about X', 'unread links'.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Search keywords, or empty string for all active unread links"},
                    "limit": {"type": "integer", "default": 10}
                },
                "required": ["query"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "link_snooze",
            "description": "Snooze a link so it won't appear in digests until a future date.",
            "parameters": {
                "type": "object",
                "properties": {
                    "link_id": {"type": "integer"},
                    "snooze_until": {"type": "string", "description": "ISO8601 datetime or natural language like '1 week', '3 days'"}
                },
                "required": ["link_id", "snooze_until"]
            }
        }
    },
    # ── Digest ────────────────────────────────────────────────────────────────
    {
        "type": "function",
        "function": {
            "name": "digest_get",
            "description": "Get the current digest: unread links and open ideas. Use for 'show digest', 'what's on my plate', 'backlog'.",
            "parameters": {"type": "object", "properties": {}, "required": []}
        }
    },
]


# ─── TOOL EXECUTOR ─────────────────────────────────────────────────────────────

def _parse_snooze_until(raw: str) -> datetime:
    """Convert natural language or ISO string to a concrete datetime."""
    now = datetime.now(TZ)
    raw_lower = raw.lower().strip()
    
    # Natural language shortcuts
    if "1 hour" in raw_lower or "1h" in raw_lower:
        return now + timedelta(hours=1)
    if "hour" in raw_lower:
        import re
        m = re.search(r"(\d+)\s*hour", raw_lower)
        return now + timedelta(hours=int(m.group(1)) if m else 1)
    if "1 day" in raw_lower or "1d" in raw_lower or "tomorrow" in raw_lower:
        return now + timedelta(days=1)
    if "day" in raw_lower:
        import re
        m = re.search(r"(\d+)\s*day", raw_lower)
        return now + timedelta(days=int(m.group(1)) if m else 1)
    if "1 week" in raw_lower or "1w" in raw_lower or "week" in raw_lower:
        import re
        m = re.search(r"(\d+)\s*week", raw_lower)
        return now + timedelta(weeks=int(m.group(1)) if m else 1)
    
    # Try ISO parse
    try:
        dt = datetime.fromisoformat(raw)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=TZ)
        return dt
    except Exception:
        return now + timedelta(days=1)


def _parse_timeframe(timeframe: str) -> tuple[datetime, datetime]:
    """Parse a timeframe string into (start, end) datetime pair."""
    from datetime import date
    now = datetime.now(TZ)
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    
    t = timeframe.lower().strip()
    if t == "today":
        return today_start, today_start + timedelta(days=1)
    if t == "tomorrow":
        return today_start + timedelta(days=1), today_start + timedelta(days=2)
    if "this week" in t:
        week_start = today_start - timedelta(days=now.weekday())
        return week_start, week_start + timedelta(days=7)
    if "next week" in t:
        week_start = today_start - timedelta(days=now.weekday()) + timedelta(days=7)
        return week_start, week_start + timedelta(days=7)
    if "next" in t:
        # "next Monday" etc — find next occurrence of that weekday
        days_map = {"monday": 0, "tuesday": 1, "wednesday": 2, "thursday": 3,
                    "friday": 4, "saturday": 5, "sunday": 6}
        for day_name, day_num in days_map.items():
            if day_name in t:
                delta = (day_num - now.weekday() + 7) % 7 or 7
                target = today_start + timedelta(days=delta)
                return target, target + timedelta(days=1)
    
    # Try ISO date string
    try:
        d = date.fromisoformat(timeframe)
        start = datetime(d.year, d.month, d.day, tzinfo=TZ)
        return start, start + timedelta(days=1)
    except Exception:
        pass
    
    # Default to today
    return today_start, today_start + timedelta(days=1)


async def _execute_tool(name: str, args: dict) -> str:
    """Execute a tool call and return a string result for the LLM."""
    try:
        if name == "calendar_query":
            from core.calendar_ops import get_events_in_range, detect_conflicts
            start, end = _parse_timeframe(args["timeframe"])
            events = get_events_in_range(start, end)
            if not events:
                return f"No events found for '{args['timeframe']}'."
            
            # Check for conflicts and surface them
            conflicts = detect_conflicts(events)
            lines = [f"📅 Events for {args['timeframe']} ({len(events)} total):"]
            for ev in events:
                try:
                    ev_dt = datetime.fromisoformat(ev['start']).astimezone(TZ)
                    time_str = ev_dt.strftime("%a %d %b %I:%M %p")
                except Exception:
                    time_str = ev['start']
                lines.append(f"• [{ev['id'][:8]}] {ev['title']} — {time_str}")
            
            if conflicts:
                lines.append("\n⚠️ Conflicts detected:")
                for a, b in conflicts:
                    lines.append(f"  ↳ '{a['title']}' overlaps with '{b['title']}'")
            
            return "\n".join(lines)

        elif name == "calendar_create":
            from core.calendar_ops import create_event, get_events_in_range, detect_conflicts
            ev = create_event(
                title=args["title"],
                start=args["start_datetime"],
                end=args["end_datetime"],
                description=args.get("description", ""),
            )
            # Check for conflicts with the new event
            try:
                ev_start = datetime.fromisoformat(args["start_datetime"])
                ev_end = datetime.fromisoformat(args["end_datetime"])
                if ev_start.tzinfo is None:
                    ev_start = ev_start.replace(tzinfo=TZ)
                if ev_end.tzinfo is None:
                    ev_end = ev_end.replace(tzinfo=TZ)
                window = get_events_in_range(
                    ev_start - timedelta(hours=1),
                    ev_end + timedelta(hours=1)
                )
                # Filter to only overlapping events (excluding the one just created)
                conflicts = [
                    e for e in window
                    if e['id'] != ev['id'] and _events_overlap(e, ev)
                ]
            except Exception:
                conflicts = []
            
            result = f"✅ Created: '{ev['title']}' on {ev['start']}"
            if conflicts:
                result += f"\n⚠️ CONFLICT: overlaps with '{conflicts[0]['title']}'"
            return result

        elif name == "calendar_update":
            from core.calendar_ops import find_event_by_reference, update_event
            ev = find_event_by_reference(args["event_reference"])
            if not ev:
                return f"❌ No event found matching '{args['event_reference']}'."
            updated = update_event(ev["id"], args["changes"])
            return f"✅ Updated '{updated['title']}' → {updated['start']}"

        elif name == "calendar_delete":
            from core.calendar_ops import find_event_by_reference, delete_event
            ev = find_event_by_reference(args["event_reference"])
            if not ev:
                return f"❌ No event found matching '{args['event_reference']}'."
            ok = delete_event(ev["id"])
            return f"✅ Deleted '{ev['title']}'." if ok else f"❌ Failed to delete '{ev['title']}'."

        elif name == "calendar_find_free_slots":
            from core.calendar_ops import find_free_slots
            slots = find_free_slots(
                duration_minutes=args["duration_minutes"],
                within_days=args.get("within_days", 7),
            )
            if not slots:
                return "No free slots found in that window."
            lines = [f"🕐 Free {args['duration_minutes']}min slots:"]
            for s in slots:
                try:
                    dt = datetime.fromisoformat(s["start"]).astimezone(TZ)
                    lines.append(f"• {dt.strftime('%a %d %b, %I:%M %p')}")
                except Exception:
                    lines.append(f"• {s['start']}")
            return "\n".join(lines)

        elif name == "idea_capture":
            result = await _capture_idea_pipeline(args["text"])
            return f"Captured idea #{result['id']} tagged [{result['tag']}]. Summary: {result['summary']}"

        elif name == "idea_delete":
            await archive_idea(args["idea_id"])
            return f"Deleted idea #{args['idea_id']}."

        elif name == "idea_query":
            q = args.get("query", "")
            limit = args.get("limit", 10)
            if q:
                ideas = await search_ideas(q)
            else:
                ideas = await get_active_ideas(limit=limit)
            if not ideas:
                return "No ideas found." + (f" Searched for: '{q}'" if q else "")
            lines = [f"💡 Ideas ({len(ideas)} found):"]
            for idea in ideas[:limit]:
                tag = idea.get("tags", "misc")
                summary = idea.get("summary") or idea["text"][:60]
                lines.append(f"• #{idea['id']} [{tag}] {summary}")
            return "\n".join(lines)

        elif name == "idea_snooze":
            wake_at = _parse_snooze_until(args["snooze_until"])
            await snooze_item("idea", args["idea_id"], wake_at)
            wake_str = wake_at.strftime("%d %b at %I:%M %p")
            return f"Snoozed idea #{args['idea_id']} until {wake_str}."

        elif name == "link_capture":
            await asyncio.get_event_loop().run_in_executor(None, lambda: None)  # yield
            result = await _capture_link_pipeline(args["url"])
            return (
                f"Saved link #{result['id']} [{result['tag']}]\n"
                f"Title: {result['title']}\n"
                f"Summary: {result['summary']}"
            )

        elif name == "link_delete":
            await archive_link(args["link_id"])
            return f"Deleted link #{args['link_id']}."

        elif name == "link_mark_read":
            await mark_link_read(args["link_id"])
            return f"Marked link #{args['link_id']} as read."

        elif name == "link_query":
            q = args.get("query", "")
            limit = args.get("limit", 10)
            if q:
                links = await search_links(q)
            else:
                links = await get_active_links(limit=limit)
            if not links:
                return "No links found." + (f" Searched for: '{q}'" if q else "")
            lines = [f"🔗 Links ({len(links)} found):"]
            for lnk in links[:limit]:
                tag = lnk.get("tags", "misc")
                summary = lnk.get("summary") or lnk["url"]
                title = lnk.get("title") or lnk["url"][:50]
                lines.append(f"• #{lnk['id']} [{tag}] {title}\n  {summary[:80]}")
            return "\n".join(lines)

        elif name == "link_snooze":
            wake_at = _parse_snooze_until(args["snooze_until"])
            await snooze_item("link", args["link_id"], wake_at)
            wake_str = wake_at.strftime("%d %b at %I:%M %p")
            return f"Snoozed link #{args['link_id']} until {wake_str}."

        elif name == "digest_get":
            from core.digest import build_digest
            digest = await build_digest()
            parts = []
            if digest["ideas"]:
                parts.append(f"💡 Ideas ({len(digest['ideas'])}):")
                for idea in digest["ideas"]:
                    tag = idea.get("tags", "misc")
                    summary = idea.get("summary") or idea["text"][:60]
                    parts.append(f"  #{idea['id']} [{tag}] {summary}")
            if digest["links"]:
                parts.append(f"🔗 Links ({len(digest['links'])}):")
                for lnk in digest["links"]:
                    tag = lnk.get("tags", "misc")
                    title = lnk.get("title") or lnk["url"][:40]
                    summary = lnk.get("summary", "")[:80]
                    parts.append(f"  #{lnk['id']} [{tag}] {title}\n    {summary}")
            if not parts:
                return "Your backlog is clear — nothing pending."
            return "\n".join(parts)

        else:
            return f"Unknown tool: {name}"

    except Exception as e:
        return f"Tool error ({name}): {e}"


def _events_overlap(a: dict, b: dict) -> bool:
    """Check if two calendar event dicts overlap in time."""
    try:
        a_start = datetime.fromisoformat(a["start"])
        a_end = datetime.fromisoformat(a["end"])
        b_start = datetime.fromisoformat(b["start"])
        b_end = datetime.fromisoformat(b["end"])
        return a_start < b_end and b_start < a_end
    except Exception:
        return False


# ─── SYSTEM PROMPT ─────────────────────────────────────────────────────────────

def _build_system_prompt() -> str:
    now = datetime.now(TZ)
    return f"""You are a personal assistant for Chin (0xsteamboat). Today is {now.strftime('%A, %d %B %Y, %I:%M %p %Z')}.

You have full tool access to manage calendar, ideas, and links. Every message should be reasoned about before responding:
- Is this a command on something we just discussed? (use context from conversation history)
- Is this a new capture? (idea or link)
- Is this a calendar action?
- Is this a query or question?

Key behaviors:
- When the user says "delete this", "archive that", "snooze this" — infer the item from context (what was just discussed/shown)
- When capturing an idea or link, always call the appropriate tool — don't just reply with text
- When creating a calendar event, always check for conflicts and flag them immediately
- Be concise. Confirm what you actually did, not what you're about to do.
- For queries, show the data — don't just describe it.
- If a request is ambiguous, make the most reasonable interpretation and do it.

You manage three domains: Calendar (Google Calendar), Ideas (quick thoughts/notes), Links (read-later queue with summaries).

Do NOT capture "delete this please" or command-like messages as ideas. Reason about intent first."""


# ─── MAIN AGENT LOOP ───────────────────────────────────────────────────────────

async def run_agent_turn(chat_id: str, user_message: str) -> str:
    """
    Full agent turn: history → LLM → tool loop → reply.
    This is the ONLY entry point from the bot layer.
    """
    # 1. Load history
    history = await get_history(str(chat_id))
    
    # 2. Append the new user message
    await append_message(str(chat_id), "user", user_message)
    
    # 3. Build message list for LLM
    messages = [
        {"role": "system", "content": _build_system_prompt()}
    ] + history + [
        {"role": "user", "content": user_message}
    ]
    
    # 4. Agentic tool-call loop (max 6 iterations to prevent runaway)
    final_reply = None
    tool_loop_messages = messages.copy()
    
    for _ in range(6):
        resp = await acompletion(
            model=MODEL,
            messages=tool_loop_messages,
            tools=TOOLS,
            tool_choice="auto",
            temperature=0.3,
            max_tokens=1000,
        )
        
        choice = resp.choices[0]
        msg = choice.message
        
        if choice.finish_reason == "tool_calls" and msg.tool_calls:
            # Execute all tool calls in this response
            tool_results = []
            for tc in msg.tool_calls:
                args = {}
                try:
                    args = json.loads(tc.function.arguments)
                except Exception:
                    pass
                
                result = await _execute_tool(tc.function.name, args)
                tool_results.append({
                    "tool_call_id": tc.id,
                    "role": "tool",
                    "content": result,
                })
            
            # Add the assistant tool-call message + results to the loop
            tool_loop_messages.append({
                "role": "assistant",
                "content": msg.content,
                "tool_calls": [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {
                            "name": tc.function.name,
                            "arguments": tc.function.arguments,
                        }
                    }
                    for tc in msg.tool_calls
                ],
            })
            tool_loop_messages.extend(tool_results)
            
        else:
            # Final text reply
            final_reply = (msg.content or "").strip()
            break
    
    if not final_reply:
        final_reply = "Done."
    
    # 5. Persist assistant reply to history
    await append_message(str(chat_id), "assistant", final_reply)
    await clear_old_history(str(chat_id))
    
    return final_reply
