"""
Gmail triage — read-only.
Shares the Google OAuth token with Calendar (core/google_auth.py).
Never sends, drafts, labels, or deletes anything — fetch + summarize only.
"""

from core.google_auth import get_google_service


def _header(msg: dict, name: str) -> str:
    for h in msg.get("payload", {}).get("headers", []):
        if h["name"].lower() == name.lower():
            return h["value"]
    return ""


def fetch_recent_messages(max_results: int = 10, query: str = "is:unread") -> list[dict]:
    """Returns [{id, from, subject, snippet}, ...] for the most recent matching messages."""
    svc = get_google_service("gmail", "v1")
    result = svc.users().messages().list(userId="me", q=query, maxResults=max_results).execute()
    ids = [m["id"] for m in result.get("messages", [])]

    messages = []
    for mid in ids:
        msg = svc.users().messages().get(
            userId="me", id=mid, format="metadata", metadataHeaders=["From", "Subject"]
        ).execute()
        messages.append({
            "id": mid,
            "from": _header(msg, "From"),
            "subject": _header(msg, "Subject"),
            "snippet": msg.get("snippet", ""),
        })
    return messages
