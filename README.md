# Personal Assistant

A Telegram-based personal assistant, built to run on Hermes (my always-on home server). **Hermes is the brain.** The bot is a thin interface.

## Architecture

```
You (Telegram)
      ↕
Bot (python-telegram-bot) — interface only, no business logic
      ↕
core/ — agent loop, todos, habits, ideas, links, calendar, email, digest, briefing, alerts
      ↕
┌──────────────────┬─────────────┬───────────────────┐
Google Calendar+Gmail   SQLite DB     LiteLLM (any model)
```

## Phase 1 Scope
- ✅ Telegram bot wired to Hermes
- ✅ Calendar CRUD + daily agenda briefing (silent on empty days)
- ✅ Todos: capture, categorize, priority, due dates, recurrence, calendar time-blocking
- ✅ Habit tracking: passive logging + streaks
- ✅ Idea capture: capture + categorize + summarize
- ✅ Link capture: fetch + summarize + categorize
- ✅ Email triage: read-only Gmail summarization on demand
- ✅ Daily digest: todos, ideas, links, habit streaks (items marked shown, no re-dump)
- ✅ Morning briefing: calendar agenda + due/overdue todos (silent on empty days)
- ✅ Out-of-band alert path wired for conflicts + urgent events

## Setup

### 1. Install dependencies
```bash
cd ~/Documents/personal-assistant
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### 2. Configure
```bash
cp .env.example .env
# Edit .env with your values
```

**Required values:**
- `PA_BOT_TOKEN` — from @BotFather on Telegram
- `PA_CHAT_ID` — your personal chat ID (message @userinfobot)
- `ANTHROPIC_API_KEY` (or another provider's key — see .env.example)
- Google Calendar credentials (see step 3)

### 3. Google Calendar + Gmail auth (one-time)
Calendar and Gmail (read-only, for email triage) share one OAuth token — enable both APIs up front:
1. Go to [console.cloud.google.com](https://console.cloud.google.com)
2. Create project → Enable **Google Calendar API** and **Gmail API**
3. APIs & Services → Credentials → Create **OAuth 2.0 Client ID** (Desktop app)
4. Download JSON → save as `credentials/google_credentials.json`
5. Run: `python3 scripts/setup_google_auth.py`

If you already authorized this app for Calendar only (before email triage was added), delete `credentials/token.json` and re-run the script so the new `gmail.readonly` scope gets consented to.

### 4. Run the bot
```bash
source venv/bin/activate
python3 -m bot.main
```

## Cron Jobs (set up in Hermes)

| Job | Schedule | Script |
|-----|----------|--------|
| Morning briefing | 08:00 SGT daily | `scripts/morning_briefing.py` |
| Daily digest | 20:00 SGT daily | `scripts/daily_digest.py` |

## Triage Commands

Nothing below is special syntax the parser requires — the agent understands natural phrasing. These are just example phrasings.

| Command | Action |
|---------|--------|
| `remind me to renew my passport by Friday` | Capture a todo with a due date |
| `complete todo 3` | Mark todo #3 done (auto-spawns next occurrence if recurring) |
| `delete todo 3` | Abandon todo #3 without completing it |
| `what's due today` | Show due/overdue todos |
| `block 30 min for todo 3` | Time-block todo #3 onto the calendar's next free slot |
| `did my workout today` | Log a habit occurrence for today |
| `how's my streak` | Show all tracked habits + streaks |
| `check my email` | Triage recent unread Gmail (read-only) |
| `archive i3` | Archive idea #3 |
| `archive l7` | Archive link #7 |
| `read l7` | Mark link #7 as read |
| `snooze i3 7d` | Snooze idea #3 for 7 days |
| `snooze l4 3h` | Snooze link #4 for 3 hours |
| `digest` | Show backlog digest now |
| `show ideas about X` | Search ideas |
| `show links about X` | Search links |
| `briefing` | Show today's calendar |

## Model Swap

Change `PA_LLM_MODEL` in `.env`. LiteLLM handles routing.
No code changes needed.

## Skills Added This Build

Six domains the agent now manages, all reachable through plain conversation (no slash syntax required). What each does and how to get the most out of it:

### 1. Todos — capture, categorize, prioritize, schedule
Actionable tasks, distinct from ideas (passing thoughts). Auto-tagged by the LLM (same freeform pattern as ideas/links — no fixed category list to maintain), with priority (high/medium/low, inferred from your phrasing if you don't state it), optional due dates, and optional recurrence.
- **Maximize it:** state urgency/deadline naturally ("pay rent by the 5th, this is important") — the model reads priority and due date straight out of the sentence, no separate fields needed.
- **Recurring tasks**: say "every Monday" / "daily" / "weekdays" once; completing an occurrence auto-spawns the next one — you never re-type a recurring chore.
- **Calendar time-blocking**: "block 45 min for todo 3" reuses the existing free-slot finder to actually put the task on your calendar, linked back to the todo.
- Surfaces automatically: due/overdue todos appear in the 8am morning briefing; the full open list appears in the 8pm digest.

### 2. Habit tracking — passive log + streaks
No daily check-in prompt to ignore. Mention a routine happening ("went for a run", "meditated") and it's normalized to a habit name, logged for today (idempotent — mentioning it twice doesn't double-count), and streaks accrue automatically.
- **Maximize it:** be consistent with how you phrase a given habit early on — the LLM fuzzy-matches to existing habit names, so "workout" and "did my workout" collapse into one habit, but wildly different phrasing can create a duplicate. Ask "show my habits" occasionally to catch and consolidate drift.
- Streaks + today's status show up in every evening digest — a free accountability nudge with zero extra setup.

### 3. Calendar management — full CRUD + conflict + free-slot intelligence
Already the most mature piece: create/update/delete/query events via natural language, automatic overlap/conflict detection on every read and write, and free-slot finding across a work-hours window.
- **Maximize it:** don't bother with exact ISO timestamps — "move my 3pm to tomorrow" and "find me 30 minutes this week" both work. Conflicts are flagged the moment they're created, not discovered later.

### 4. Email triage (Gmail, read-only) — on demand
"Check my email" pulls recent unread mail and has the LLM flag which need action versus which are FYI/noise, with a one-line summary each. Strictly read-only — it cannot send, draft, label, or delete anything, by design (least-privilege OAuth scope: `gmail.readonly`).
- **Maximize it:** ask it before triaging your inbox manually — it front-loads the "does this need me" decision so you only open the 2 that matter instead of scanning 40.

### 5. Idea capture — capture, categorize, summarize (pre-existing, kept as-is)
Freeform thought capture with auto-tagging and summarization for anything long. This is the container for non-actionable notes; todos now handle the actionable ones, keeping this list from being cluttered with tasks.

### 6. Link capture — fetch, summarize, categorize (pre-existing, kept as-is)
Send a URL, get the page fetched, summarized, and tagged automatically into a read-later queue.

**System-wide leverage point:** all six domains run through one agent loop (`core/agent.py`) with full conversation memory, so you never need to remember which "mode" you're in — say what you want, and it infers todo vs. idea vs. calendar vs. habit vs. email intent from context, including references to "that" or "this" from a few messages back.

## Future Considerations (researched, not built this round)

Scoped out for now to keep this build tight — worth revisiting:

- **Proactive same-day urgent nudges** — push the moment a todo goes overdue or an event is imminent, instead of waiting for the next scheduled briefing/digest. Needs a new frequent cron check (e.g. every 30 min) rather than piggybacking on existing jobs.
- **Email drafting** — have the assistant draft replies (saved to Gmail drafts, never auto-sent) instead of just summarizing. Needs a broader Gmail OAuth scope (`gmail.compose`).
- **Expense/budget tracking** — capture "spent $40 on groceries" the same way ideas/todos are captured, with monthly category rollups.
- **Journaling / daily reflection** — a nightly "how was today" prompt, stored and searchable, distinct from habit streaks (qualitative vs. quantitative).
- **Contact & birthday reminders** — surface upcoming birthdays/anniversaries from Google Contacts in the morning briefing.
- **Weather-aware briefing** — fold a weather API call into the morning briefing for context on the day.
- **Voice message transcription** — Telegram voice notes → transcribed → routed through the same capture pipeline (todo/idea/etc.), useful for capturing on the move.
- **Meeting prep** — auto-summarize an upcoming meeting's context (attendees, linked docs, related past events) shortly before it starts.
- **Semantic search over captured history** — vector search across ideas/links/todos so "what did I save about X six months ago" works even without exact keyword overlap.
- **Third-party task sync** — two-way sync with Todoist/Things/Apple Reminders if you already live in one of those, instead of this being the sole source of truth.
- **Multi-channel interface** — same core/ agent reachable from WhatsApp/iMessage/Slack, not just Telegram, since the bot layer is already a thin, swappable interface.

## Phase 2 (next)
- Inline triage buttons in digest (replace text commands)
- Digest decay/prioritization logic (deprioritize old items)
- Conflict detection on every calendar write

## Phase 3 (later)
- Smart scheduling: auto-block study sessions from a course
- Slot-finding for backlog follow-ups
