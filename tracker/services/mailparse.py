from __future__ import annotations

import re
from dataclasses import dataclass

from tracker.constants import OpportunityStatus, SHEET_STATUS_FROM_FULL, SHEET_STATUS_RANK
from tracker.models import Application, Opportunity
from tracker.services import extract
from tracker.services.extract import SEASON_OPTIONS, clean_role_title, extract_please_note, infer_season  # noqa: F401
from tracker.services.text import normalize_skill
from tracker.services.workflow import change_status, initialize_opportunity

STATUS_FROM_RESULT = {
    "Applied": OpportunityStatus.APPLIED,
    "OA": OpportunityStatus.ONLINE_ASSESSMENT,
    "Interview": OpportunityStatus.INTERVIEWING,
    "Offer": OpportunityStatus.OFFER,
    "Rejected": OpportunityStatus.REJECTED,
}


@dataclass
class MailHint:
    company: str
    title: str
    status: str
    confidence: float
    note: str
    source_id: str = ""
    thread_id: str = ""
    date_applied: str = ""
    location: str = ""
    season: str = ""
    source_url: str = ""
    useful_note: str = ""
    application_key: str = ""
    tab: str = ""
    previous_key: str = ""


def gmail_url_from_thread(thread_id: str) -> str:
    if not thread_id:
        return ""
    return f"https://mail.google.com/mail/u/0/#all/{thread_id}"


def compose_notes(useful_note: str, source_url: str = "") -> str:
    parts = []
    if useful_note:
        parts.append(useful_note)
    if source_url:
        parts.append(f"Source: {source_url}")
    return "\n".join(parts)


def infer_notes(body: str, thread_id: str = "") -> str:
    return compose_notes(extract_please_note(body), gmail_url_from_thread(thread_id))


def parse_message(
    from_header: str,
    subject: str,
    body: str,
    source_id: str = "",
    thread_id: str = "",
    date_applied: str = "",
) -> MailHint | None:
    from tracker.services.gsheet import application_key, format_applied_date

    parsed = extract.parse_mail(from_header, subject, body)
    if not parsed:
        return None
    source_url = gmail_url_from_thread(thread_id)
    return MailHint(
        company=parsed["company"],
        title=parsed["role"],
        status=STATUS_FROM_RESULT[parsed["result"]],
        confidence=float(parsed.get("confidence") or 0.5),
        note=compose_notes(parsed["useful_note"], source_url),
        source_id=source_id,
        thread_id=thread_id,
        # Only the confirmation date is the applied date; OA / rejection dates are not.
        date_applied=format_applied_date(date_applied) if parsed["confirmation"] else "",
        location=parsed["location"],
        season=parsed["season"],
        source_url=source_url,
        useful_note=parsed["useful_note"],
        application_key=application_key(parsed["company"], parsed["role"], parsed["season"]),
        tab=parsed["tab"],
    )


def parse_pasted_emails(raw: str) -> list[MailHint]:
    chunks = re.split(r"\n(?=From: )", raw.strip())
    hints: list[MailHint] = []
    if len(chunks) == 1 and "From:" not in raw:
        hint = parse_message("", "", raw)
        return [hint] if hint else []
    for chunk in chunks:
        from_match = re.search(r"^From:\s*(.+)$", chunk, flags=re.M)
        subject_match = re.search(r"^Subject:\s*(.+)$", chunk, flags=re.M)
        hint = parse_message(
            from_match.group(1) if from_match else "",
            subject_match.group(1) if subject_match else "",
            chunk,
        )
        if hint:
            hints.append(hint)
    return hints


def _norm_company(name: str) -> str:
    text = normalize_skill(name)
    for suffix in (" inc", " llc", " ltd", " corp", " co", " recruiting"):
        if text.endswith(suffix):
            text = text[: -len(suffix)].strip()
    return text


PARSER_VERSION = 12


def to_sheet_hint(hint: MailHint):
    from tracker.services.gsheet import SheetHint, application_key, result_label

    return SheetHint(
        company=hint.company,
        role=hint.title,
        location=hint.location,
        tab=hint.tab or "internships",
        result=result_label(hint.status),
        notes=hint.note,
        date_applied=hint.date_applied,
        season=hint.season,
        location_missing=not bool(hint.location),
        source_url=hint.source_url,
        useful_note=hint.useful_note,
        application_key=hint.application_key or application_key(hint.company, hint.title, hint.season),
        previous_key=hint.previous_key,
    )


def _match_opportunity(
    user, company: str, title: str = "", status: str = OpportunityStatus.APPLIED
) -> tuple[Opportunity | None, str]:
    from tracker.services.gsheet import is_generic_role, is_placeholder, normalize_company

    if len(_norm_company(company)) < 2:
        return None, "skipped"
    queryset = Opportunity.objects.filter(user=user, is_archived=False)
    token = _norm_company(company).split(" ")[0]
    if len(token) >= 3:
        queryset = queryset.filter(company__icontains=token)
    matches = [opp for opp in queryset if extract.companies_match(opp.company, company)]
    if not matches:
        return None, "create"
    role_hits = [opp for opp in matches if normalize_company(opp.title) == normalize_company(title)]
    if len(role_hits) == 1:
        return role_hits[0], "update"
    if len(role_hits) > 1:
        return None, "review"
    if len(matches) == 1:
        current_title = matches[0].title
        # OA / interview / offer / rejection mail is about an application you already have, even if it words the role differently.
        if (
            not title
            or is_generic_role(title)
            or is_placeholder(current_title)
            or normalize_company(current_title) == normalize_company(title)
            or (status != OpportunityStatus.APPLIED and extract.roles_similar(current_title, title))
        ):
            return matches[0], "update"
        return None, "create"
    if len(matches) > 1 and is_generic_role(title):
        return None, "review"
    return None, "create"


def _title_is_better(current: str, hinted: str) -> bool:
    from tracker.services.gsheet import role_should_replace

    return role_should_replace(current, hinted)


def _applied_datetime(value: str):
    from datetime import datetime

    from django.utils import timezone

    from tracker.services.gsheet import format_applied_date

    text = format_applied_date(value)
    if not text:
        return None
    try:
        return timezone.make_aware(datetime.strptime(text, "%m/%d/%Y"))
    except ValueError:
        return None


def _source_thread_id(line: str) -> str:
    url = re.sub(r"(?i)^source:\s*", "", str(line or "")).strip()
    match = re.search(r"([0-9a-f]{10,})", url, re.I)
    return match.group(1).lower() if match else ""


def _merge_note_text(current: str, incoming: str) -> str:
    """Keep one Source line per Gmail thread, preferring the longer URL."""
    out: list[str] = []
    source_at: dict[str, int] = {}
    for raw in f"{current or ''}\n{incoming or ''}".split("\n"):
        part = raw.strip()
        if not part:
            continue
        if part.lower().startswith("source:"):
            thread_id = _source_thread_id(part)
            key = thread_id or part.lower()
            if key in source_at:
                if len(part) > len(out[source_at[key]]):
                    out[source_at[key]] = part
                continue
            url = re.sub(r"(?i)^source:\s*", "", part).strip()
            replaced = False
            for index, existing in enumerate(out):
                if not existing.lower().startswith("source:"):
                    continue
                other = re.sub(r"(?i)^source:\s*", "", existing).strip()
                if other.startswith(url) or url.startswith(other):
                    if len(part) > len(existing):
                        out[index] = part
                    source_at[key] = index
                    replaced = True
                    break
            if replaced:
                continue
            source_at[key] = len(out)
            out.append(part)
            continue
        if part not in out:
            out.append(part)
    return "\n".join(out)


def apply_mail_hints(user, hints: list[MailHint]) -> dict:
    created = 0
    updated = 0
    skipped = 0
    review = 0
    for hint in hints:
        if not (hint.confidence >= 0.9):
            review += 1
            hint.disposition = "review"
            continue
        existing, action = _match_opportunity(user, hint.company, hint.title, hint.status)
        if action == "review":
            review += 1
            hint.disposition = "review"
            continue
        hint.disposition = "applied"
        if existing:
            fields_changed = False
            if _title_is_better(existing.title, hint.title):
                existing.title = hint.title
                fields_changed = True
            if hint.location and not existing.location:
                existing.location = hint.location
                fields_changed = True
            merged_notes = _merge_note_text(existing.notes or "", hint.note)
            if merged_notes != (existing.notes or ""):
                existing.notes = merged_notes
                fields_changed = True
            if fields_changed:
                existing.save()
            applied_at = _applied_datetime(hint.date_applied)
            if applied_at:
                application, _ = Application.objects.get_or_create(opportunity=existing)
                if application.applied_at is None:
                    application.applied_at = applied_at
                    application.save(update_fields=["applied_at"])
                    fields_changed = True
            current = SHEET_STATUS_FROM_FULL.get(existing.status, existing.status)
            current_rank = SHEET_STATUS_RANK.get(current, 0)
            next_rank = SHEET_STATUS_RANK.get(hint.status, 0)
            if current == OpportunityStatus.OFFER and hint.status == OpportunityStatus.REJECTED:
                if fields_changed:
                    updated += 1
                else:
                    skipped += 1
                continue
            if hint.status == OpportunityStatus.APPLIED and existing.status not in {
                OpportunityStatus.SAVED,
                OpportunityStatus.APPLIED,
            }:
                if fields_changed:
                    updated += 1
                else:
                    skipped += 1
                continue
            offer_beats_reject = hint.status == OpportunityStatus.OFFER and current == OpportunityStatus.REJECTED
            if next_rank > current_rank or hint.status == OpportunityStatus.REJECTED or offer_beats_reject:
                change_status(existing, hint.status, hint.note, applied_at=applied_at)
                updated += 1
            elif fields_changed:
                updated += 1
            else:
                skipped += 1
            continue
        opportunity = Opportunity.objects.create(
            user=user,
            company=hint.company,
            title=hint.title or "",
            location=hint.location,
            status=OpportunityStatus.SAVED,
            notes=hint.note,
            source="other",
        )
        initialize_opportunity(opportunity)
        change_status(opportunity, hint.status, hint.note, applied_at=_applied_datetime(hint.date_applied))
        created += 1
    return {"created": created, "updated": updated, "skipped": skipped, "review": review}
