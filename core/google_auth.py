"""
Shared Google OAuth credential loader.
Calendar (read/write) and Gmail (readonly) share a single token —
scopes must cover both, so this is the single source of truth for both.
Run scripts/setup_google_auth.py once (or again, after adding a scope) to
generate/refresh token.json.
"""

import os

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

SCOPES = [
    "https://www.googleapis.com/auth/calendar",
    "https://www.googleapis.com/auth/gmail.readonly",
]
CREDS_PATH = os.getenv("GOOGLE_CALENDAR_CREDS_PATH", "credentials/google_credentials.json")
TOKEN_PATH = os.getenv("GOOGLE_TOKEN_PATH", "credentials/token.json")


def get_google_credentials() -> Credentials:
    creds = None
    if os.path.exists(TOKEN_PATH):
        creds = Credentials.from_authorized_user_file(TOKEN_PATH, SCOPES)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(CREDS_PATH, SCOPES)
            creds = flow.run_local_server(port=0)
        os.makedirs(os.path.dirname(TOKEN_PATH), exist_ok=True)
        with open(TOKEN_PATH, "w") as f:
            f.write(creds.to_json())
    return creds


def get_google_service(api_name: str, api_version: str):
    return build(api_name, api_version, credentials=get_google_credentials(), cache_discovery=False)
