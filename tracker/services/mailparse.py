from __future__ import annotations

import re
from dataclasses import dataclass
from email.utils import parseaddr

from tracker.constants import OpportunityStatus, SHEET_STATUS_FROM_FULL, SHEET_STATUS_RANK
from tracker.models import Opportunity
from tracker.services.text import normalize_skill
from tracker.services.workflow import change_status, initialize_opportunity

PLATFORM_DOMAINS = {
    "lever.co",
    "greenhouse.io",
    "myworkdayjobs.com",
    "workday.com",
    "ashbyhq.com",
    "icims.com",
    "smartrecruiters.com",
    "taleo.net",
    "successfactors.com",
    "linkedin.com",
    "indeed.com",
    "simplify.jobs",
}

GENERIC_MAIL = {"gmail.com", "googlemail.com", "outlook.com", "hotmail.com", "yahoo.com", "icloud.com", "me.com"}

SKIP_LOCAL = {"noreply", "no-reply", "mailer-daemon", "notifications"}


@dataclass
class MailHint:
    company: str
    title: str
    status: str
    confidence: float
    note: str
    source_id: str = ""


def _company_from_domain(email_addr: str) -> str:
    _, addr = parseaddr(email_addr or "")
    domain = addr.split("@")[-1].lower() if "@" in addr else ""
    host = domain.split(":")[0]
    parts = [p for p in host.split(".") if p not in {"www", "mail", "email", "careers", "jobs", "recruiting", "talent", "hr"}]
    if not parts:
        return ""
    root = ".".join(parts[-2:]) if len(parts) >= 2 else parts[-1]
    if root in PLATFORM_DOMAINS or parts[-1] in {"edu"}:
        return ""
    if host in GENERIC_MAIL or root in GENERIC_MAIL:
        return ""
    name = parts[-2] if len(parts) >= 2 else parts[0]
    if name in {"co", "com", "io"}:
        name = parts[-3] if len(parts) >= 3 else name
    return name.replace("-", " ").title()


def _contains_any(blob: str, phrases: tuple[str, ...]) -> bool:
    return any(phrase in blob for phrase in phrases)


def infer_status(text: str) -> tuple[str | None, float]:
    blob = text.lower()
    if _contains_any(blob, ("offer of employment", "we are pleased to offer", "congratulations on your offer")):
        return OpportunityStatus.OFFER, 0.9
    if _contains_any(
        blob,
        (
            "unfortunately",
            "not moving forward",
            "moving forward with other",
            "will not be moving",
            "position has been filled",
            "not selected",
        ),
    ):
        return OpportunityStatus.REJECTED, 0.86
    if _contains_any(
        blob,
        (
            "online assessment",
            "hackerrank",
            "codesignal",
            "codility",
            "oa invitation",
            "complete the assessment",
        ),
    ):
        return OpportunityStatus.ONLINE_ASSESSMENT, 0.88
    if _contains_any(
        blob,
        (
            "interview invitation",
            "invite you to interview",
            "schedule your interview",
            "book your interview",
            "phone screen",
            "recruiter screen",
        ),
    ):
        return OpportunityStatus.INTERVIEWING, 0.86
    if _contains_any(
        blob,
        (
            "thank you for applying",
            "application received",
            "we have received your application",
            "application was submitted",
            "thanks for your application",
        ),
    ):
        return OpportunityStatus.APPLIED, 0.84
    return None, 0.0


def infer_company(from_header: str, subject: str, body: str) -> str:
    display, _addr = parseaddr(from_header or "")
    from_name = re.sub(r"(recruiting|careers|talent|university|noreply|no-reply)", "", display, flags=re.I).strip(" -|")
    if from_name and len(from_name) < 80 and "@" not in from_name:
        lowered = from_name.lower()
        if lowered not in {"jobs", "careers", "recruiting", "talent acquisition"}:
            return re.sub(r"\s+", " ", from_name)
    domain_company = _company_from_domain(from_header)
    if domain_company:
        return domain_company
    patterns = [
        r"thank you for applying to ([^!.\n]+)",
        r"application (?:to|for) ([^!.\n]+)",
        r"your application to ([^!.\n]+)",
        r"interview with ([^!.\n]+)",
    ]
    blob = f"{subject}\n{body}"
    for pattern in patterns:
        match = re.search(pattern, blob, flags=re.I)
        if match:
            return match.group(1).strip(" *")[:120]
    return ""


def infer_title(subject: str, body: str) -> str:
    blob = f"{subject}\n{body[:1500]}"
    match = re.search(
        r"(intern(?:ship)?|co-?op|new grad)[^.\n]{0,60}",
        blob,
        flags=re.I,
    )
    if match:
        return re.sub(r"\s+", " ", match.group(0)).strip()[:200]
    return "Internship"


def parse_message(from_header: str, subject: str, body: str, source_id: str = "") -> MailHint | None:
    text = f"{subject}\n{body}"
    status, confidence = infer_status(text)
    company = infer_company(from_header, subject, body)
    if not status or not company or confidence < 0.75:
        return None
    return MailHint(
        company=company[:200],
        title=infer_title(subject, body),
        status=status,
        confidence=confidence,
        note=f"From email: {subject[:180]}",
        source_id=source_id,
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


def _match_opportunity(user, company: str) -> Opportunity | None:
    target = _norm_company(company)
    if len(target) < 2:
        return None
    matches = [
        opp
        for opp in Opportunity.objects.filter(user=user, is_archived=False)
        if _norm_company(opp.company) == target
    ]
    return matches[0] if len(matches) == 1 else None


def apply_mail_hints(user, hints: list[MailHint]) -> dict:
    created = 0
    updated = 0
    skipped = 0
    for hint in hints:
        existing = _match_opportunity(user, hint.company)
        if existing:
            current = SHEET_STATUS_FROM_FULL.get(existing.status, existing.status)
            current_rank = SHEET_STATUS_RANK.get(current, 0)
            next_rank = SHEET_STATUS_RANK.get(hint.status, 0)
            if current == OpportunityStatus.OFFER and hint.status == OpportunityStatus.REJECTED:
                skipped += 1
                continue
            offer_beats_reject = (
                hint.status == OpportunityStatus.OFFER and current == OpportunityStatus.REJECTED
            )
            if next_rank > current_rank or hint.status == OpportunityStatus.REJECTED or offer_beats_reject:
                change_status(existing, hint.status, hint.note)
                if hint.note and hint.note not in (existing.notes or ""):
                    existing.notes = f"{hint.note}\n{existing.notes}".strip()
                    existing.save(update_fields=["notes", "updated_at"])
                updated += 1
            else:
                skipped += 1
            continue
        opportunity = Opportunity.objects.create(
            user=user,
            company=hint.company,
            title=hint.title,
            status=OpportunityStatus.SAVED,
            notes=hint.note,
            source="other",
        )
        initialize_opportunity(opportunity)
        change_status(opportunity, hint.status, hint.note)
        created += 1
    return {"created": created, "updated": updated, "skipped": skipped}
