"""
Personal Assistant Bot — main entry point.
Starts the python-telegram-bot Application with async handlers.
"""

import asyncio
import logging
import os
from pathlib import Path

from dotenv import load_dotenv

# Load .env relative to project root (one level up from this file)
load_dotenv(Path(__file__).parent / ".env")

from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters

from core.db import init_db
from bot.handlers import handle_message, cmd_start, cmd_digest, cmd_briefing

logging.basicConfig(
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger("pa.bot")


async def post_init(application):
    await init_db()
    logger.info("DB initialized.")


def main():
    token = os.environ.get("PA_BOT_TOKEN")
    if not token:
        raise RuntimeError("PA_BOT_TOKEN not set. Copy .env.example → .env and fill in your token.")

    app = (
        Application.builder()
        .token(token)
        .post_init(post_init)
        .build()
    )

    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("help", cmd_start))
    app.add_handler(CommandHandler("digest", cmd_digest))
    app.add_handler(CommandHandler("briefing", cmd_briefing))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    logger.info("Bot starting — polling…")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
