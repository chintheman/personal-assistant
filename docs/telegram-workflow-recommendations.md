# Telegram Communication Workflow — Recommendations for Hermes

Hermes (`core/agent.py`) is the brain; Telegram is the only channel it has to think out loud,
ask, confirm, and interrupt. Today that channel is a single, undifferentiated pipe: every
reply is one `sendMessage` call, HTML-formatted, fire-and-forget. This doc reviews how that
pipe is actually used today, what breaks or wastes effort as a result, and a prioritized set
of changes to make Telegram a proper communication layer for an agentic loop rather than a
dumb print statement.

Method: read every file in `bot/` and `core/` involved in sending or receiving a Telegram
message (`bot/main.py`, `bot/handlers.py`, `bot/formatters.py`, `core/agent.py`,
`core/alerts.py`, `core/calendar_handler.py`, `core/conversation.py`, `core/digest.py`,
`core/briefing.py`, `core/llm.py`), traced every call site of the alert/notification path,
and cross-checked against current python-telegram-bot / Telegram Bot API guidance on inline
keyboards, message-length limits, and flood control.

---

## TL;DR

| # | Recommendation | Priority | Effort | Type |
|---|---|---|---|---|
| 1 | Escape/guard all HTML sent to Telegram | P0 | S | Bug |
| 2 | Wrap every `sendMessage`/`reply_text` in a plain-text fallback | P0 | S | Bug |
| 3 | Fix history pruning to not split tool-call/tool-result pairs | P0 | S | Bug |
| 4 | Wire urgency + conflict alerts into the *live* agent path | P0 | M | Bug |
| 5 | Chunk outgoing text at 4096 chars | P0 | S | Bug |
| 6 | Inline-keyboard triage (replace `archive i3` text commands) | P1 | M | UX |
| 7 | Typing-indicator heartbeat for multi-tool turns | P1 | S | UX |
| 8 | Live step narration during the tool loop (edit-in-place) | P1 | M | UX |
| 9 | Confirm-before-delete for calendar (hard delete only) | P1 | S | UX/Safety |
| 10 | Use `disable_notification` based on urgency | P1 | S | UX |
| 11 | Retry/backoff + 429 handling on outbound sends | P2 | S | Robustness |
| 12 | Pin `concurrent_updates=False` explicitly + document why | P2 | S | Robustness |
| 13 | Durable logging for failed cron pushes | P2 | S | Robustness |
| 14 | Idempotency guard on cron-triggered sends | P2 | S | Robustness |
| 15 | "Undo" for ideas/links (cheap — already soft-deleted) | P2 | S | UX |
| 16 | Forum topics per domain (Calendar/Ideas/Links/Alerts) | P3 | L | UX (optional) |

P0 = fix regardless of scope, these are live bugs. P1 = the actual "communication workflow"
ask. P2/P3 = hardening and stretch goals.

---

## 1. Bugs in the current channel (P0)

### 1.1 Unescaped HTML will eventually break a reply
`bot/formatters.py` and `bot/handlers.py` interpolate raw strings — idea text, link titles,
LLM-generated summaries, the agent's own free-text reply (`bot/handlers.py:42`) — directly
into `parse_mode="HTML"` messages. None of it is escaped. The moment a captured idea contains
`<3`, an unclosed `<`, or a link title with a stray `&`, Telegram's HTML parser rejects the
`sendMessage` call with a 400 ("can't parse entities"). Since this content is user- and
LLM-generated (link titles are scraped from arbitrary web pages in `core/links.py`), it's not
a hypothetical — it's a matter of time.

**Fix:** escape dynamic segments with `html.escape()` before interpolating, or move to
`parse_mode="MarkdownV2"` with disciplined escaping, or simplest: only use HTML tags in the
literal template text you control and escape every variable substitution.

### 1.2 One bad character drops the whole reply, silently
`bot/handlers.py:42` calls `update.message.reply_text(reply, parse_mode="HTML")` outside any
`try/except` — only the agent turn itself is guarded. If that call fails (see 1.1, or a 4096
overflow, see 1.5), the exception propagates and python-telegram-bot's default error handling
just logs it; the user gets nothing and no idea Hermes actually did the work.

**Fix:** wrap every outbound send in a helper that retries once with `parse_mode=None` (plain
text) on a `BadRequest`, so formatting bugs degrade gracefully instead of eating the message.

### 1.3 History pruning can corrupt the tool-call transcript
`core/conversation.py:clear_old_history` keeps the newest `MAX_HISTORY=20` **rows**,
regardless of role. But a single agentic turn can produce an `assistant` message with
`tool_calls` followed by one-or-more `tool` role messages — this fixed-size cutoff can trim
the assistant message but leave the paired `tool` message (or vice versa). Every LLM provider
behind LiteLLM rejects a `tool` message that isn't immediately preceded by its matching
`tool_calls` — so the *next* turn's `acompletion()` call can fail outright, and the failure
mode is "the bot silently stops responding," which is the worst possible failure mode for a
personal assistant.

**Fix:** prune in whole-turn units (walk back from the newest row and always cut at a
`user`-role boundary), not by raw row count.

### 1.4 The out-of-band alert path is wired to dead code
The README claims "✅ Out-of-band alert path wired for conflicts + urgent events," and
`core/alerts.py`'s docstring says the same. In reality:
- `alert_calendar_conflict()` is only called from `core/calendar_handler.py:76` —
  a legacy NLU-based calendar handler that **nothing imports** (`bot/main.py` never
  references it, and `core/agent.py`'s tool loop has its own inline conflict check that just
  returns text — it never calls `core/alerts.py`).
- `alert_upcoming_event()` has no caller anywhere in the codebase.
- `assess_urgency()` in `core/llm.py` is defined but never invoked.

So today, a conflict created through the actual live path (the `calendar_create` tool in
`core/agent.py`) only shows up as inline text in that one reply — if the user doesn't see
that message (phone off, notification missed), there is no second, out-of-band nudge, despite
that being the documented design goal.

**Fix:** call `core/alerts.py` functions from `core/agent.py`'s `_execute_tool` (calendar
create/update paths) instead of the orphaned `calendar_handler.py`, and actually invoke
`assess_urgency()` somewhere in the loop — either in the digest/briefing scripts, or as a
post-hoc check whenever a calendar tool detects a conflict or a near-term event. Then delete
`calendar_handler.py` — it's unreferenced dead code that will otherwise keep drifting from the
real behavior.

### 1.5 No handling for Telegram's 4096-character message cap
Digest/idea/link listings grow with backlog size and are currently sent as one string with no
length check. Once a reply crosses 4096 characters, `sendMessage` returns 400 and — per 1.2 —
the whole reply is lost, not truncated.

**Fix:** chunk on line boundaries before sending (split into ≤4096-char pieces, sent as
sequential messages), in both `bot/handlers.py`'s reply path and `core/alerts.py:send_alert`.

---

## 2. The actual ask: a better communication workflow (P1)

### 2.1 Inline-keyboard triage instead of memorized text commands
Right now triage is entirely command-syntax: `archive i3`, `snooze l4 3h`, `read l7`. Every
one of these round-trips through the full agent loop — history load, system prompt, an LLM
call to route intent, a tool call, another LLM call to phrase the confirmation — to execute
what is, functionally, a single button press. This is the exact gap the README's own Phase 2
section already names ("Inline triage buttons in digest").

Attach an `InlineKeyboardMarkup` to every digest/query item (`Archive` / `Snooze` / `Read`),
routed through a single `CallbackQueryHandler` with a `type:action:id` callback-data
convention (e.g. `idea:archive:42`). Benefits, concretely:
- Zero LLM calls for the common case — cuts latency and token cost per triage action to ~0.
- No syntax to remember or get wrong (`snooze l4 3h` vs `snooze link 4 for 3 hours` are both
  "valid" today only because the LLM is lenient — a button can't be typo'd).
- Telegram answers the tap with `answerCallbackQuery` (a lightweight toast), which is faster
  visual feedback than waiting for a full agent turn.

Keep the natural-language path as-is for anything that isn't a rote action — buttons
complement the agent loop, they don't replace it.

### 2.2 Typing indicator expires mid-turn on multi-tool turns
`ChatAction.TYPING` auto-hides after ~5 seconds of inactivity on Telegram's side. `run_agent_turn`
can do up to 6 LLM round trips plus tool calls that hit the Google Calendar API or fetch/summarize
a web page — comfortably over 5 seconds. Today `handle_message` sends the typing action exactly
once (`bot/handlers.py:34`), so on anything but the fastest turns the indicator disappears while
Hermes is still working, and the user has no signal anything is happening.

**Fix:** a small background task that re-sends `send_chat_action(TYPING)` every ~4s for the
duration of `run_agent_turn`, cancelled when the turn resolves.

### 2.3 No visibility into what's happening during a multi-step turn
Beyond the typing dot, the user gets nothing until the final reply — no indication whether
Hermes is checking the calendar, fetching a URL, or waiting on the LLM. For a genuinely
agentic multi-tool turn (e.g. "move my 3pm to 5pm and tell me if that clashes with anything"),
that's a long silent wait for something that's actually doing several distinct steps.

**Fix:** send one status message at turn start, then `edit_message_text` it after each tool
call in the loop with a short label (`🔧 Checking calendar…` → `🔧 Rescheduling…` → the final
answer replaces it in place). Throttle edits to roughly 1/sec per chat to stay under Telegram's
flood limits — with a max-6-iteration loop this is well within bounds.

### 2.4 No confirmation before irreversible calendar deletes
`idea_delete` / `link_delete` are soft deletes (`archived=1` — see `core/db.py`), fully
reversible. `calendar_delete`, however, calls Google Calendar's real delete API
(`core/calendar_ops.py:delete_event`) — and the event to delete is resolved by **fuzzy
substring match on title** (`find_event_by_reference`) or by the agent inferring "this/that"
from conversation context (`core/agent.py`'s system prompt explicitly tells it to do this).
A wrong fuzzy match silently deletes the wrong real-world event with no undo.

**Fix:** only for `calendar_delete` (and `calendar_update` when the reference was inferred
rather than given explicitly), send an inline confirm/cancel keyboard before executing. Don't
add this friction to idea/link deletes — those are cheap to reverse (see 2.5) and confirming
every one would just add round trips to a low-stakes action.

### 2.5 Add "undo" instead of confirming everything
Since idea/link archiving is already a soft delete, an "Undo" button on the confirmation toast
of an archive action is nearly free: it's just un-setting `archived`. This gets the safety
benefit of confirmation without the friction of asking first — the better trade-off for
reversible actions, whereas irreversible ones (2.4) genuinely need ask-first.

### 2.6 Every message pings the same way, regardless of urgency
`core/alerts.py:send_alert` never sets `disable_notification`, so a routine 8pm digest and a
genuine "your calendar has a conflict in 20 minutes" alert produce an identical
buzz/sound. `assess_urgency()` in `core/llm.py` already exists to classify exactly this — it's
just never called (see 1.4).

**Fix:** once urgency assessment is wired in, pass `disable_notification=not urgent` through
`send_alert`. Routine digests/briefings should be silent-arrival by default; genuine conflicts
and near-term-event nudges should ring.

---

## 3. Hardening (P2)

- **Retry/backoff on send failures.** `send_alert`'s `except` clause just prints and drops the
  message — including transient network blips and Telegram's own 429 `retry_after` responses.
  A cron-triggered morning briefing that fails to send due to a momentary network hiccup is
  gone forever with no record. Add one retry with the `retry_after` value Telegram returns on
  429, and one general backoff retry on other transient errors.
- **Make sequential-per-chat processing explicit.** python-telegram-bot defaults
  `concurrent_updates` to `False` (sequential), which is why the conversation-history
  read/append in `core/conversation.py` is safe today. That safety is implicit, though — pin
  `Application.builder().concurrent_updates(False)` explicitly in `bot/main.py` with a comment
  explaining why, so a future "let's speed things up" change doesn't quietly introduce a
  history race condition.
- **Durable failure logging for cron scripts.** `scripts/morning_briefing.py` and
  `daily_digest.py` only `print()` on failure — if cron doesn't capture stdout somewhere
  durable, a failed push vanishes with no trace. Log to a file or a small `failed_sends` table
  that a later run can retry/report on.
- **Idempotency on cron sends.** Neither cron script checks whether it already sent today —
  a duplicate cron trigger (or a manual re-run while debugging) double-sends the briefing or
  digest. A `last_sent_date` check (or reusing `digest_log`) closes this cheaply.

## 4. Optional / longer-term (P3)

- **Forum topics per domain.** If usage ever outgrows a single linear DM thread, Telegram's
  forum-topic support (`message_thread_id`) could split Calendar / Ideas / Links / Alerts into
  separate topics within one chat. Not worth it at current scope — flagging only because it's
  the natural next step if backlog volume grows enough that a single thread gets noisy.

---

## Suggested sequencing

1. **P0 bug pass first** — these are correctness issues that will bite regardless of any UX
   work layered on top, and several (1.3, 1.4) actively contradict what the README claims is
   already shipped.
2. **P1 inline-keyboard triage (2.1)** — highest leverage single change; it's already the
   named Phase 2 goal and directly reduces LLM round trips for the most common interaction.
3. **P1 confirm/undo pair (2.4/2.5)** — cheap, and closes the one real safety gap (irreversible
   calendar deletes via fuzzy matching).
4. **P1 typing heartbeat + step narration (2.2/2.3)** — polish once the above is solid.
5. **P2 hardening** — whenever the cron/alert path gets touched next.
