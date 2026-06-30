# Personal Assistant

A Telegram-based personal assistant. **Hermes is the brain.** The bot is a thin interface.

## Architecture

```
You (Telegram)
      ↕
Bot (python-telegram-bot) — interface only, no business logic
      ↕
core/ — routing, NLU, ideas, links, calendar, digest, alerts
      ↕
┌──────────────┬─────────────┬───────────────────┐
Google Calendar   SQLite DB     LiteLLM (any model)
```

## Phase 1 Scope
- ✅ Telegram bot wired to Hermes
- ✅ Calendar CRUD + daily agenda briefing (silent on empty days)
- ✅ Idea capture: capture + categorize + summarize
- ✅ Link capture: fetch + summarize + categorize
- ✅ Daily digest: basic (items marked shown, no re-dump)
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

### 3. Google Calendar auth (one-time)
1. Go to [console.cloud.google.com](https://console.cloud.google.com)
2. Create project → Enable **Google Calendar API**
3. APIs & Services → Credentials → Create **OAuth 2.0 Client ID** (Desktop app)
4. Download JSON → save as `credentials/google_credentials.json`
5. Run: `python3 scripts/setup_google_auth.py`

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

| Command | Action |
|---------|--------|
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

## Phase 2 (next)
- Inline triage buttons in digest (replace text commands)
- Digest decay/prioritization logic (deprioritize old items)
- Conflict detection on every calendar write

## Phase 3 (later)
- Smart scheduling: auto-block study sessions from a course
- Slot-finding for backlog follow-ups
