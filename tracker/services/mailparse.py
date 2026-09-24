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


JUNK_COMPANY = {
    "jobs",
    "careers",
    "recruiting",
    "talent",
    "talent acquisition",
    "talent acquisition team",
    "no reply",
    "noreply",
    "no-reply",
    "do not reply",
    "notifications",
    "mailer daemon",
}


def _clean_company(name: str) -> str:
    text = re.sub(r"(recruiting|careers|talent acquisition team|talent acquisition|university|noreply|no-reply|do not reply)", "", name or "", flags=re.I)
    text = re.sub(r"\s+", " ", text).strip(" -|*,")
    if not text or text.lower() in JUNK_COMPANY or "@" in text or len(text) > 80:
        return ""
    return text


def infer_company(from_header: str, subject: str, body: str) -> str:
    blob = f"{subject}\n{body}"
    patterns = [
        r"thank you for applying to ([^.\n]+)",
        r"thank you for your interest in ([^.\n]+)",
        r"your application to ([^.\n]+)",
        r"application to ([^.\n]+)",
        r"interview with ([^.\n]+)",
    ]
    for pattern in patterns:
        match = re.search(pattern, blob, flags=re.I)
        if match:
            company = _clean_company(match.group(1))
            if company:
                return company[:120]
    display, _addr = parseaddr(from_header or "")
    from_name = _clean_company(display)
    if from_name:
        return from_name
    return _company_from_domain(from_header)


def _clean_title(title: str) -> str:
    text = re.sub(r"\s+", " ", title or "").strip(" -:*,")
    text = re.sub(r"^(?:the|a|an)\s+", "", text, flags=re.I)
    text = re.sub(r"\s+role$", "", text, flags=re.I)
    text = re.sub(r"^(?:position|role)\s+of\s+", "", text, flags=re.I)
    return text.strip()[:200]


def infer_title(subject: str, body: str) -> str:
    blob = f"{subject}\n{body[:4000]}"
    patterns = [
        r"(?:the\s+)?(?:position|role)\s+of\s+([^.\n]+)",
        r"application for(?: the)?(?: position of| role of)?\s+([^.\n]+)",
        r"for the\s+([^.\n]*?(?:intern(?:ship)?|co-?op|new grad)[^.\n]*)",
        r"((?:software|firmware|hardware|data|machine learning|electrical|mechanical|product|research)[^.\n]{0,60}(?:intern(?:ship)?|co-?op|new grad))",
    ]
    for pattern in patterns:
        match = re.search(pattern, blob, flags=re.I)
        if not match:
            continue
        title = _clean_title(match.group(1))
        if len(title) >= 4 and title.lower() not in {"the", "this", "your application"}:
            return title
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


PARSER_VERSION = 4


def _title_tokens(title: str) -> set[str]:
    stop = {"the", "a", "an", "of", "and", "for", "role", "position"}
    return {part for part in normalize_skill(title).split() if part and part not in stop}


def _titles_match(left: str, right: str) -> bool:
    a = normalize_skill(left)
    b = normalize_skill(right)
    if not a or not b:
        return False
    if a == b or a in b or b in a:
        return True
    return len(_title_tokens(left) & _title_tokens(right)) >= 2


def _match_opportunity(user, company: str, title: str = "") -> Opportunity | None:
    target = _norm_company(company)
    if len(target) < 2:
        return None
    matches = [
        opp
        for opp in Opportunity.objects.filter(user=user, is_archived=False)
        if _norm_company(opp.company) == target
    ]
    if not matches:
        return None
    if len(matches) == 1:
        return matches[0]
    titled = [opp for opp in matches if _titles_match(opp.title, title)]
    if len(titled) == 1:
        return titled[0]
    return None


def _title_is_better(current: str, hinted: str) -> bool:
    now = (current or "").strip()
    nxt = (hinted or "").strip()
    if not nxt:
        return False
    generic = {"intern", "internship", "role", "position"}
    if now.lower() in generic and nxt.lower() not in generic:
        return True
    return len(nxt) > len(now) + 6 and "intern" in nxt.lower()


def apply_mail_hints(user, hints: list[MailHint]) -> dict:
    created = 0
    updated = 0
    skipped = 0
    for hint in hints:
        existing = _match_opportunity(user, hint.company, hint.title)
        if existing:
            fields_changed = False
            if _title_is_better(existing.title, hint.title):
                existing.title = hint.title
                existing.save(update_fields=["title", "updated_at"])
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
            offer_beats_reject = (
                hint.status == OpportunityStatus.OFFER and current == OpportunityStatus.REJECTED
            )
            if next_rank > current_rank or hint.status == OpportunityStatus.REJECTED or offer_beats_reject:
                change_status(existing, hint.status, hint.note)
                if hint.note and hint.note not in (existing.notes or ""):
                    existing.notes = f"{hint.note}\n{existing.notes}".strip()
                    existing.save(update_fields=["notes", "updated_at"])
                updated += 1
            elif fields_changed:
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
