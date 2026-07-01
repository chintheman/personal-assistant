#!/usr/bin/env python3
"""
Google OAuth setup script — console flow (M1/headless safe).
Run ONCE. Prints a URL you open on any browser, you paste back the code.
After that, the bot auto-refreshes credentials forever.

Usage:
  cd ~/Documents/personal-assistant
  python3 scripts/setup_google_auth.py
"""

import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from dotenv import load_dotenv
load_dotenv(PROJECT_ROOT / ".env")

from google_auth_oauthlib.flow import Flow

from core.google_auth import SCOPES, CREDS_PATH, TOKEN_PATH


def main():
    creds_file = PROJECT_ROOT / CREDS_PATH
    if not creds_file.exists():
        print(f"❌ Credentials file not found: {creds_file}")
        sys.exit(1)

    flow = Flow.from_client_secrets_file(
        str(creds_file),
        scopes=SCOPES,
        redirect_uri="urn:ietf:wg:oauth:2.0:oob",
    )

    auth_url, _ = flow.authorization_url(prompt="consent", access_type="offline")

    print("\n" + "=" * 60)
    print("Step 1 — Open this URL in your browser (M4 is fine):\n")
    print(auth_url)
    print("\n" + "=" * 60)
    print("Step 2 — Log in with your Google account and click Allow.")
    print("Step 3 — Google will show a code. Copy it and paste it below.\n")

    code = input("Paste the authorization code: ").strip()

    flow.fetch_token(code=code)
    creds = flow.credentials

    token_path = PROJECT_ROOT / TOKEN_PATH
    token_path.parent.mkdir(parents=True, exist_ok=True)
    with open(token_path, "w") as f:
        f.write(creds.to_json())

    print(f"\n✅ Token saved to {token_path}")
    print("You're all set — the bot will auto-refresh from now on.")


if __name__ == "__main__":
    main()
