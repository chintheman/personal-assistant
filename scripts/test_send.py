#!/usr/bin/env python3
"""Send a test message to the PA bot and wait for a response."""
import httpx, time, sys
sys.path.insert(0, ".")
from dotenv import load_dotenv
load_dotenv(".env")
import os

token = os.environ["PA_BOT_TOKEN"]
chat_id = os.environ["PA_CHAT_ID"]

# Send a test idea
r = httpx.post(
    f"https://api.telegram.org/bot{token}/sendMessage",
    json={"chat_id": chat_id, "text": "test idea: what if I built a newsletter about AI agents"},
    timeout=5
)
print(f"Send status: {r.status_code} {r.json().get('ok', False)}")
print(f"  Response: {r.json().get('result', {}).get('text', 'N/A')[:100]}")
time.sleep(4)

# Check for bot's reply
r2 = httpx.get(f"https://api.telegram.org/bot{token}/getUpdates", params={"timeout": 1, "limit": 5}, timeout=5)
data = r2.json()
if data.get("result"):
    for u in data["result"]:
        msg = u.get("message", {})
        text = msg.get("text", "")
        is_bot = msg.get("from", {}).get("is_bot", False)
        if is_bot:
            print(f"\nBot replied: {text[:200]}")
else:
    print(f"\nNo bot response detected")
