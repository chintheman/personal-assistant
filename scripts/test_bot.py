#!/usr/bin/env python3
"""Test PA bot — send a message and check for response."""
import httpx, re, sys
sys.path.insert(0, ".")
from dotenv import load_dotenv
load_dotenv(".env")
import os

token = os.environ["PA_BOT_TOKEN"]
chat_id = os.environ["PA_CHAT_ID"]

# Check recent messages
r = httpx.get(f"https://api.telegram.org/bot{token}/getUpdates", params={"timeout": 1, "limit": 10}, timeout=5)
data = r.json()
if data.get("result"):
    for u in data["result"][-5:]:
        msg = u.get("message", {}).get("text", "")
        bot = u.get("message", {}).get("from", {}).get("is_bot", False)
        cid = u.get("message", {}).get("chat", {}).get("id", "")
        print(f"{'🤖' if bot else '👤'} chat={cid}: {msg[:150]}")
else:
    print(f"Updates check: {r.text[:200]}")
