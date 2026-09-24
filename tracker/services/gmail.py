from __future__ import annotations

import json
from datetime import datetime, timezone as dt_timezone

from django.conf import settings
from django.urls import reverse

SCOPES = [
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/spreadsheets",
]
GMAIL_QUERY = (
    "newer_than:30d "
    "(subject:application OR subject:applied OR subject:interview OR subject:assessment "
    "OR subject:hackerrank OR subject:codesignal OR subject:offer OR subject:unfortunately "
    "OR from:recruiting OR from:careers OR from:talent OR from:university)"
)


def gmail_configured() -> bool:
    return bool(getattr(settings, "GOOGLE_OAUTH_CLIENT_ID", "") and getattr(settings, "GOOGLE_OAUTH_CLIENT_SECRET", ""))


def _client_config(request) -> dict:
    redirect_uri = getattr(settings, "GOOGLE_OAUTH_REDIRECT_URI", "") or request.build_absolute_uri(reverse("gmail_callback"))
    return {
        "web": {
            "client_id": settings.GOOGLE_OAUTH_CLIENT_ID,
            "client_secret": settings.GOOGLE_OAUTH_CLIENT_SECRET,
            "redirect_uris": [redirect_uri],
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
        }
    }


def flow_for(request):
    from google_auth_oauthlib.flow import Flow

    redirect_uri = getattr(settings, "GOOGLE_OAUTH_REDIRECT_URI", "") or request.build_absolute_uri(reverse("gmail_callback"))
    flow = Flow.from_client_config(_client_config(request), scopes=SCOPES)
    flow.redirect_uri = redirect_uri
    return flow


def credentials_from_json(raw: str):
    from google.oauth2.credentials import Credentials

    data = json.loads(raw)
    return Credentials(
        token=data.get("token"),
        refresh_token=data.get("refresh_token"),
        token_uri=data.get("token_uri", "https://oauth2.googleapis.com/token"),
        client_id=settings.GOOGLE_OAUTH_CLIENT_ID,
        client_secret=settings.GOOGLE_OAUTH_CLIENT_SECRET,
        scopes=data.get("scopes") or SCOPES,
    )


def credentials_to_json(creds) -> str:
    return json.dumps(
        {
            "token": creds.token,
            "refresh_token": creds.refresh_token,
            "token_uri": creds.token_uri,
            "scopes": list(creds.scopes or SCOPES),
        }
    )


def _header_map(payload: dict) -> dict[str, str]:
    headers = payload.get("headers") or []
    return {item.get("name", "").lower(): item.get("value", "") for item in headers}


def _decode_parts(payload: dict) -> str:
    import base64

    chunks: list[str] = []

    def walk(part: dict) -> None:
        mime = part.get("mimeType", "")
        body = part.get("body") or {}
        data = body.get("data")
        if data and mime.startswith("text/"):
            chunks.append(base64.urlsafe_b64decode(data.encode("utf-8")).decode("utf-8", errors="ignore"))
        for child in part.get("parts") or []:
            walk(child)

    walk(payload)
    return "\n".join(chunks)[:8000]


def fetch_job_messages(creds, newer_than_days: int = 30) -> list[dict]:
    from googleapiclient.discovery import build

    service = build("gmail", "v1", credentials=creds, cache_discovery=False)
    query = GMAIL_QUERY.replace("30d", f"{newer_than_days}d")
    response = service.users().messages().list(userId="me", q=query, maxResults=50).execute()
    messages = []
    for item in response.get("messages") or []:
        full = (
            service.users()
            .messages()
            .get(userId="me", id=item["id"], format="full")
            .execute()
        )
        payload = full.get("payload") or {}
        headers = _header_map(payload)
        messages.append(
            {
                "id": full.get("id"),
                "from": headers.get("from", ""),
                "subject": headers.get("subject", ""),
                "date": headers.get("date", ""),
                "body": _decode_parts(payload) or full.get("snippet", ""),
            }
        )
    return messages


def refresh_if_needed(creds):
    if creds.expired and creds.refresh_token:
        from google.auth.transport.requests import Request

        creds.refresh(Request())
    return creds
