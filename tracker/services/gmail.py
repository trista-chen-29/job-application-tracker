from __future__ import annotations

import json
from datetime import datetime, timezone as dt_timezone

from django.conf import settings
from django.urls import reverse

SCOPES = [
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/spreadsheets",
]
# Same search as GMAIL_QUERY_TERMS in sheets-addon/Code.gs.
GMAIL_QUERY = (
    "newer_than:730d "
    '(subject:"thank you for applying" OR subject:"thanks for applying" OR subject:"application received" OR '
    'subject:"we have received your application" OR subject:"thank you for your application" OR '
    'subject:"your application" OR subject:"application confirmation" OR subject:"application to" OR '
    'subject:"application for" OR subject:"applying to" OR subject:"thank you for your interest" OR '
    'subject:"online assessment" OR subject:hackerrank OR subject:codesignal OR subject:"interview invitation" OR '
    'subject:"phone screen" OR subject:"offer of employment" OR subject:unfortunately OR '
    "from:recruiting OR from:careers OR from:university OR from:talent OR from:hiring OR "
    "from:myworkday.com OR from:greenhouse-mail.io OR from:ashbyhq.com OR from:icims.com OR "
    "from:lever.co OR from:smartrecruiters.com)"
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
    if len(plain_text) >= 80 and _body_has_specific_role(plain_text):
        combined = plain_text
    elif _body_has_specific_role(html_text) and not _body_has_specific_role(plain_text):
        combined = html_text if len(plain_text) < 80 else f"{plain_text}\n{html_text}"
    elif len(plain_text) >= 80:
        combined = plain_text
    else:
        combined = "\n".join(part for part in (plain_text, html_text) if part)
    return combined[:20000]


def _body_has_specific_role(text: str) -> bool:
    if not text:
        return False
    from tracker.services.extract import clean_role_title, infer_raw_role, is_generic_role

    role = clean_role_title(infer_raw_role("", text))
    return bool(role) and not is_generic_role(role)


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


def fetch_job_messages(creds, newer_than_days: int = 730, limit: int = 40, skip_ids: set[str] | None = None) -> tuple[list[dict], bool]:
    from googleapiclient.discovery import build

    skip_ids = skip_ids or set()
    service = build("gmail", "v1", credentials=creds, cache_discovery=False)
    query = GMAIL_QUERY.replace("730d", f"{newer_than_days}d")
    ids: list[dict] = []
    page_token = None
    more = False
    pages = 0
    while len(ids) < limit and pages < 8:
        pages += 1
        kwargs = {"userId": "me", "q": query, "maxResults": min(100, max(limit * 2, 20))}
        if page_token:
            kwargs["pageToken"] = page_token
        try:
            response = _gmail_execute(service.users().messages().list(**kwargs), pause_seconds=0.2)
        except Exception:
            break
        page_token = response.get("nextPageToken")
        for item in response.get("messages") or []:
            if item["id"] in skip_ids:
                continue
            if len(ids) >= limit:
                more = True
                break
            ids.append(item)
        if len(ids) >= limit and (more or page_token):
            more = True
            break
        if not page_token:
            break
    messages = []
    for item in ids:
        try:
            full = _gmail_execute(
                service.users()
                .messages()
                .get(
                    userId="me",
                    id=item["id"],
                    format="full",
                ),
                pause_seconds=0.2,
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
    return messages, more


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
