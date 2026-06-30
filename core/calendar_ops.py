"""
Google Calendar CRUD operations.
Auth: OAuth2. Run scripts/setup_google_auth.py once to generate token.json.
All times handled in UTC; displayed in PA_TIMEZONE.
"""

import os
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

SCOPES = ["https://www.googleapis.com/auth/calendar"]
CREDS_PATH = os.getenv("GOOGLE_CALENDAR_CREDS_PATH", "credentials/google_credentials.json")
TOKEN_PATH = os.getenv("GOOGLE_TOKEN_PATH", "credentials/token.json")
TZ = ZoneInfo(os.getenv("PA_TIMEZONE", "Asia/Singapore"))
CALENDAR_ID = "primary"


def _get_service():
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
    return build("calendar", "v3", credentials=creds, cache_discovery=False)


def _now_local() -> datetime:
    return datetime.now(TZ)


def _to_rfc3339(dt: datetime) -> str:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=TZ)
    return dt.isoformat()


def _format_event(ev: dict) -> dict:
    """Normalise a Google Calendar event into our internal shape."""
    start = ev.get("start", {})
    end = ev.get("end", {})
    start_str = start.get("dateTime", start.get("date", ""))
    end_str = end.get("dateTime", end.get("date", ""))
    return {
        "id": ev["id"],
        "title": ev.get("summary", "(no title)"),
        "start": start_str,
        "end": end_str,
        "description": ev.get("description", ""),
        "location": ev.get("location", ""),
        "html_link": ev.get("htmlLink", ""),
    }


# ─── READ ───────────────────────────────────────────────────────────────────────

def get_events_for_day(date: datetime | None = None) -> list[dict]:
    """Return all events for a given calendar day (local timezone)."""
    if date is None:
        date = _now_local()
    day_start = date.replace(hour=0, minute=0, second=0, microsecond=0, tzinfo=TZ)
    day_end = day_start + timedelta(days=1)
    return get_events_in_range(day_start, day_end)


def get_events_in_range(start: datetime, end: datetime) -> list[dict]:
    svc = _get_service()
    result = svc.events().list(
        calendarId=CALENDAR_ID,
        timeMin=_to_rfc3339(start),
        timeMax=_to_rfc3339(end),
        singleEvents=True,
        orderBy="startTime",
    ).execute()
    return [_format_event(e) for e in result.get("items", [])]


def find_event_by_reference(reference: str, window_days: int = 7) -> dict | None:
    """Fuzzy-find an event by title fragment within the next N days."""
    now = _now_local()
    events = get_events_in_range(now, now + timedelta(days=window_days))
    ref_lower = reference.lower()
    for ev in events:
        if ref_lower in ev["title"].lower():
            return ev
    return None


def find_free_slots(duration_minutes: int, within_days: int = 7,
                    work_start_hour: int = 9, work_end_hour: int = 21) -> list[dict]:
    """Find free blocks of at least `duration_minutes` within working hours."""
    now = _now_local()
    end_window = now + timedelta(days=within_days)
    events = get_events_in_range(now, end_window)

    slots = []
    current = now.replace(minute=0, second=0, microsecond=0)
    if current.hour < work_start_hour:
        current = current.replace(hour=work_start_hour)

    for ev in events:
        ev_start_str = ev["start"]
        try:
            ev_start = datetime.fromisoformat(ev_start_str).astimezone(TZ)
            ev_end = datetime.fromisoformat(ev["end"]).astimezone(TZ)
        except Exception:
            continue

        gap = (ev_start - current).total_seconds() / 60
        if gap >= duration_minutes and current.hour < work_end_hour:
            # Ensure gap doesn't cross work-end boundary
            work_end_dt = current.replace(hour=work_end_hour, minute=0, second=0)
            available_gap = (min(ev_start, work_end_dt) - current).total_seconds() / 60
            if available_gap >= duration_minutes:
                slots.append({"start": _to_rfc3339(current), "end": _to_rfc3339(current + timedelta(minutes=duration_minutes))})
        current = max(current, ev_end)

    # After last event, check remaining time in work day / next days
    while len(slots) < 5 and current < end_window:
        if current.hour >= work_end_hour:
            current = (current + timedelta(days=1)).replace(hour=work_start_hour, minute=0, second=0)
        work_end_dt = current.replace(hour=work_end_hour, minute=0, second=0)
        available = (work_end_dt - current).total_seconds() / 60
        if available >= duration_minutes:
            slots.append({"start": _to_rfc3339(current), "end": _to_rfc3339(current + timedelta(minutes=duration_minutes))})
        current = current + timedelta(hours=1)

    return slots[:5]


def detect_conflicts(events: list[dict]) -> list[tuple[dict, dict]]:
    """Return pairs of overlapping events."""
    conflicts = []
    for i, a in enumerate(events):
        for b in events[i + 1:]:
            try:
                a_start = datetime.fromisoformat(a["start"]).astimezone(timezone.utc)
                a_end = datetime.fromisoformat(a["end"]).astimezone(timezone.utc)
                b_start = datetime.fromisoformat(b["start"]).astimezone(timezone.utc)
                b_end = datetime.fromisoformat(b["end"]).astimezone(timezone.utc)
                if a_start < b_end and b_start < a_end:
                    conflicts.append((a, b))
            except Exception:
                continue
    return conflicts


# ─── CREATE ─────────────────────────────────────────────────────────────────────

def create_event(title: str, start: str, end: str, description: str = "") -> dict:
    svc = _get_service()
    body = {
        "summary": title,
        "start": {"dateTime": start, "timeZone": str(TZ)},
        "end": {"dateTime": end, "timeZone": str(TZ)},
        "description": description,
    }
    ev = svc.events().insert(calendarId=CALENDAR_ID, body=body).execute()
    return _format_event(ev)


# ─── UPDATE ─────────────────────────────────────────────────────────────────────

def update_event(event_id: str, changes: dict) -> dict:
    svc = _get_service()
    ev = svc.events().get(calendarId=CALENDAR_ID, eventId=event_id).execute()
    for k, v in changes.items():
        if k == "title":
            ev["summary"] = v
        elif k == "start":
            ev["start"] = {"dateTime": v, "timeZone": str(TZ)}
        elif k == "end":
            ev["end"] = {"dateTime": v, "timeZone": str(TZ)}
        elif k == "description":
            ev["description"] = v
    updated = svc.events().update(calendarId=CALENDAR_ID, eventId=event_id, body=ev).execute()
    return _format_event(updated)


# ─── DELETE ─────────────────────────────────────────────────────────────────────

def delete_event(event_id: str) -> bool:
    try:
        _get_service().events().delete(calendarId=CALENDAR_ID, eventId=event_id).execute()
        return True
    except HttpError:
        return False
