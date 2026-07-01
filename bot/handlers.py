"""
Telegram bot handlers — thin relay layer only.

Zero business logic here. Every inbound message is relayed to the agent
loop (core/agent.py) which reasons, calls tools, and returns a final reply.

The only things this layer handles:
- Extracting the text and chat_id from the Telegram update
- Sending a "typing..." indicator while the agent thinks
- Relaying the agent's reply back to the user
- Slash commands that are purely presentational (start, help)
"""

import os
import logging
from telegram import Update
from telegram.ext import ContextTypes
from telegram.constants import ChatAction

from core.agent import run_agent_turn

logger = logging.getLogger("pa.handlers")


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Main entry point for all inbound text messages."""
    text = update.message.text or ""
    if not text:
        return

    chat_id = str(update.message.chat_id)

    # Show typing indicator while agent thinks
    await context.bot.send_chat_action(chat_id=chat_id, action=ChatAction.TYPING)

    try:
        reply = await run_agent_turn(chat_id=chat_id, user_message=text)
    except Exception as e:
        logger.exception("Agent turn failed for chat %s: %s", chat_id, e)
        reply = "⚠️ Something went wrong processing that. Try again."

    await update.message.reply_text(reply, parse_mode="HTML")


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 <b>Personal Assistant online.</b>\n\n"
        "Just talk to me naturally:\n"
        "• Send a task → captured as a todo ('remind me to renew my passport by Friday')\n"
        "• Send a thought → captured as an idea\n"
        "• Send a URL → fetched, summarized, saved\n"
        "• Mention a routine → logged as a habit ('did my workout today')\n"
        "• Calendar commands → 'what's on today', 'create meeting Friday 2pm'\n"
        "• Queries → 'show my todos', 'what's due today', 'show my ideas', 'how's my streak', 'check my email'\n"
        "• Triage → 'complete todo 3', 'delete idea 3', 'snooze link 7 for 1 week', 'mark link 2 read'\n"
        "• Scheduling → 'block 30 min for todo 3'\n\n"
        "No special syntax needed — just tell me what you want.",
        parse_mode="HTML",
    )


async def cmd_digest(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Slash command shortcut — routes through agent so history stays consistent."""
    chat_id = str(update.message.chat_id)
    await context.bot.send_chat_action(chat_id=chat_id, action=ChatAction.TYPING)
    reply = await run_agent_turn(chat_id=chat_id, user_message="show me my digest")
    await update.message.reply_text(reply, parse_mode="HTML")


async def cmd_briefing(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Slash command shortcut — routes through agent so history stays consistent."""
    chat_id = str(update.message.chat_id)
    await context.bot.send_chat_action(chat_id=chat_id, action=ChatAction.TYPING)
    reply = await run_agent_turn(chat_id=chat_id, user_message="what's on my calendar today")
    await update.message.reply_text(reply, parse_mode="HTML")
