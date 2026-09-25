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
    "newer_than:730d "
    "(subject:application OR subject:applied OR subject:interview OR subject:assessment "
    "OR subject:hackerrank OR subject:codesignal OR subject:offer OR subject:unfortunately "
    "OR from:recruiting OR from:careers OR from:talent OR from:university "
    "OR subject:\"thank you for applying\" OR subject:\"application received\")"
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


def _html_to_text(html: str) -> str:
    import re

    text = re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>", " ", html)
    text = re.sub(r"(?i)<br\s*/?>", "\n", text)
    text = re.sub(r"(?i)</(p|div|tr|h1|h2|h3|li)>", "\n", text)
    text = re.sub(r"<[^>]+>", " ", text)
    replacements = {"&nbsp;": " ", "&amp;": "&", "&#39;": "'", "&rsquo;": "'", "&ldquo;": '"', "&rdquo;": '"'}
    for src, dst in replacements.items():
        text = text.replace(src, dst)
    return re.sub(r"[ \t]+", " ", text)


def _decode_parts(payload: dict) -> str:
    import base64

    plain: list[str] = []
    html: list[str] = []

    def walk(part: dict) -> None:
        mime = (part.get("mimeType") or "").lower()
        body = part.get("body") or {}
        data = body.get("data")
        if data and mime.startswith("text/"):
            decoded = base64.urlsafe_b64decode(data.encode("utf-8")).decode("utf-8", errors="ignore")
            if "html" in mime:
                html.append(decoded)
            else:
                plain.append(decoded)
        for child in part.get("parts") or []:
            walk(child)

    walk(payload)
    plain_text = "\n".join(plain).strip()
    html_text = _html_to_text("\n".join(html)).strip()
    if len(plain_text) >= 80:
        combined = plain_text
        if "position of" not in plain_text.lower() and "position of" in html_text.lower():
            combined = f"{plain_text}\n{html_text}"
    else:
        combined = "\n".join(part for part in (plain_text, html_text) if part)
    return combined[:20000]


def _is_rate_limit(exc) -> bool:
    text = str(exc).lower()
    return "ratelimitexceeded" in text or "quota exceeded" in text or "usagelimits" in text


def _gmail_execute(request, pause_seconds: float = 0.0):
    import time

    from googleapiclient.errors import HttpError

    if pause_seconds:
        time.sleep(pause_seconds)
    last_error = None
    for attempt in range(6):
        try:
            return request.execute()
        except HttpError as exc:
            last_error = exc
            if exc.resp.status not in {403, 429} or not _is_rate_limit(exc):
                raise
            time.sleep(20 + attempt * 15)
    raise last_error


def fetch_job_messages(creds, newer_than_days: int = 730, limit: int = 40, skip_ids: set[str] | None = None) -> list[dict]:
    from googleapiclient.discovery import build

    skip_ids = skip_ids or set()
    service = build("gmail", "v1", credentials=creds, cache_discovery=False)
    query = GMAIL_QUERY.replace("730d", f"{newer_than_days}d")
    ids: list[dict] = []
    page_token = None
    while len(ids) < 400:
        kwargs = {
            "userId": "me",
            "q": query,
            "maxResults": min(100, 400 - len(ids)),
        }
        if page_token:
            kwargs["pageToken"] = page_token
        try:
            response = _gmail_execute(service.users().messages().list(**kwargs), pause_seconds=0.4)
        except Exception:
            break
        ids.extend(response.get("messages") or [])
        page_token = response.get("nextPageToken")
        if not page_token:
            break
    messages = []
    for item in ids:
        if item["id"] in skip_ids:
            continue
        try:
            full = _gmail_execute(
                service.users()
                .messages()
                .get(
                    userId="me",
                    id=item["id"],
                    format="full",
                ),
                pause_seconds=1.3,
            )
        except Exception:
            break
        payload = full.get("payload") or {}
        headers = _header_map(payload)
        messages.append(
            {
                "id": full.get("id"),
                "threadId": full.get("threadId") or "",
                "from": headers.get("from", ""),
                "subject": headers.get("subject", ""),
                "date": headers.get("date", ""),
                "body": _decode_parts(payload) or full.get("snippet", ""),
            }
        )
        if len(messages) >= limit:
            break
    return messages


def fetch_messages_by_ids(creds, message_ids: list[str], limit: int = 15) -> list[dict]:
    from googleapiclient.discovery import build

    service = build("gmail", "v1", credentials=creds, cache_discovery=False)
    messages = []
    for message_id in message_ids[:limit]:
        try:
            full = _gmail_execute(
                service.users().messages().get(userId="me", id=message_id, format="full"),
                pause_seconds=1.3,
            )
        except Exception:
            break
        payload = full.get("payload") or {}
        headers = _header_map(payload)
        messages.append(
            {
                "id": full.get("id"),
                "threadId": full.get("threadId") or "",
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
